from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from core.config import LLM_CONFIG, MEMORY_CONFIG, AGENTS_CONFIG
from graph.state import GraphState
from graph.nodes import (
    pre_process, manage_memory, rewrite_query, router,
    merge_answers, update_profile, post_process,
    llm as base_llm
)
from memory import get_checkpointer
from tools import build_tools, UI_TYPE_MAP
from agents import build_all_agents


async def build_graph():
    # 建立工具 dict 與 agent 子圖
    tools_dict = build_tools()
    agent_subgraphs = build_all_agents(AGENTS_CONFIG, tools_dict, base_llm, ui_type_map=UI_TYPE_MAP)

    # 路由函數：根據 next_agents 用 Send() 實現 fan-out
    def route_by_intent(state: GraphState):
        agents = state.get("next_agents", [])

        # 只保留 summary (SystemMessage) + 當前問題 (最後一個 HumanMessage)
        # 避免舊對話的 AI 回覆影響 agent 決策 & merge_answers 計數
        agent_msgs = []
        for msg in state.get("messages", []):
            if hasattr(msg, "type") and msg.type == "system":
                agent_msgs.append(msg)
        for msg in reversed(state.get("messages", [])):
            if hasattr(msg, "type") and msg.type == "human":
                agent_msgs.append(msg)
                break

        # [DEBUG] head → agent：派發的 messages
        previews = []
        for msg in agent_msgs:
            mt = getattr(msg, "type", "unknown")
            mc = (msg.content if hasattr(msg, "content") else str(msg)).replace("\n", " ")
            previews.append(f"{mt}:{mc[:20]}")
        print(f"  [head→agent] {len(agent_msgs)} 則 → {agents}: {' | '.join(previews)}")

        clean = {**state, "history": [], "messages": agent_msgs, "ui_hints": []}

        if not agents:
            return [Send("merge_answers", clean)]
        # 過濾出有效的 agent，無效的跳過
        valid = [a for a in agents if a in agent_subgraphs]
        if not valid:
            return [Send("merge_answers", clean)]

        return [Send(a, clean) for a in valid]

    # 組裝 StateGraph
    workflow = StateGraph(GraphState)

    # 節點
    workflow.add_node("pre_process", pre_process)
    workflow.add_node("manage_memory", manage_memory)
    # workflow.add_node("rewrite_query", rewrite_query)  # 暫時停用
    workflow.add_node("router", router)
    workflow.add_node("merge_answers", merge_answers)
    workflow.add_node("update_profile", update_profile)
    workflow.add_node("post_process", post_process)

    for name, subgraph in agent_subgraphs.items():
        workflow.add_node(name, subgraph)

    # 連線
    workflow.add_edge(START, "pre_process")
    workflow.add_edge("pre_process", "manage_memory")
    # workflow.add_edge("manage_memory", "rewrite_query")  # 暫時停用
    # workflow.add_edge("rewrite_query", "router")        # 暫時停用
    workflow.add_edge("manage_memory", "router")

    # router → 各 agent / merge_answers（透過 Send() fan-out）
    workflow.add_conditional_edges("router", route_by_intent)

    # 各 agent → merge_answers
    for name in agent_subgraphs:
        workflow.add_edge(name, "merge_answers")

    # merge_answers → update_profile → post_process → END
    workflow.add_edge("merge_answers", "update_profile")
    workflow.add_edge("update_profile", "post_process")
    workflow.add_edge("post_process", END)

    # Checkpointer
    memory = await get_checkpointer(MEMORY_CONFIG)

    return workflow.compile(checkpointer=memory)
