from langgraph.graph import StateGraph, START, END
from core.config import DB_CONFIG, INTENTS_CONFIG, MEMORY_CONFIG, REQUIRED_SLOTS
from graph.state import GraphState
from memory import get_checkpointer  
from graph.nodes import (
    create_retrieve_node, detect_intent, generate_answer,
    transfer_to_human, out_of_domain, decide_sufficiency, rewrite_query,
    extract_slots, ask_missing_slots, load_user_profile, update_user_profile
)
def build_graph():
    workflow = StateGraph(GraphState)

    workflow.add_node("load_user_profile", load_user_profile)
    workflow.add_node("rewrite_query", rewrite_query)
    workflow.add_node("extract_slots", extract_slots)
    workflow.add_node("ask_missing_slots", ask_missing_slots)
    workflow.add_node("detect_intent", detect_intent)
    workflow.add_node("generate", generate_answer)
    workflow.add_node("update_user_profile", update_user_profile)
    workflow.add_node("out_of_domain", out_of_domain)
    workflow.add_node("human", transfer_to_human)

    for db in DB_CONFIG:
        workflow.add_node(db["name"], create_retrieve_node(db))

    if DB_CONFIG and INTENTS_CONFIG:
        workflow.add_edge(START, "load_user_profile")
        workflow.add_edge("load_user_profile", "rewrite_query")
        workflow.add_edge("rewrite_query", "detect_intent")
        workflow.add_edge("detect_intent", "extract_slots")

        intent_mapping = {
            intent["name"]: intent["target"]
            for intent in INTENTS_CONFIG
        }

        # 建立意圖是否需要 slot filling 的對照表
        intent_require_slots = {
            intent["name"]: intent.get("require_slots", False)
            for intent in INTENTS_CONFIG
        }

        # 合併意圖路由與缺少欄位的路由
        path_map = {**intent_mapping, "ask_missing_slots": "ask_missing_slots"}

        def route_after_extract(state: GraphState):
            current_intent = state.get("intent")

            # 只有設定 require_slots = true 的意圖才檢查必填欄位
            if intent_require_slots.get(current_intent, False):
                current_slots = state.get("slots", {})
                for key in REQUIRED_SLOTS.keys():
                    val = current_slots.get(key)
                    if not val:
                        return "ask_missing_slots"

            return current_intent
            
        workflow.add_conditional_edges(
            "extract_slots",
            route_after_extract,
            path_map
        )

        workflow.add_edge("ask_missing_slots", "update_user_profile")

        for i in range(len(DB_CONFIG)):
            current_db = DB_CONFIG[i]["name"]
            next_step = DB_CONFIG[i+1]["name"] if i + 1 < len(DB_CONFIG) else "human"
            
            def create_fallback_router(target_step):
                async def router(state: GraphState):
                    result = await decide_sufficiency(state)
                    if result == "sufficient":
                        return "generate"
                    
                    if target_step == "db_web_search":
                        current_slots = state.get("slots", {})
                        has_unknown = any(val == "UNKNOWN" for val in current_slots.values())

                        if has_unknown:
                            print("  [系統攔截] 缺乏必要設備資訊，終止外部搜尋，轉交真人處理。")
                            return "human"
                
                    return target_step
                return router
                
            workflow.add_conditional_edges(
                current_db,
                create_fallback_router(next_step),
                {"generate": "generate", next_step: next_step, "human": "human"}
            )
    else:
        workflow.add_edge(START, "human")

    workflow.add_edge("generate", "update_user_profile")
    workflow.add_edge("update_user_profile", END)
    workflow.add_edge("out_of_domain", "update_user_profile")
    workflow.add_edge("human", "update_user_profile")

    memory = get_checkpointer(MEMORY_CONFIG)

    return workflow.compile(checkpointer=memory)

app = build_graph()