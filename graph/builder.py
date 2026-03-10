from langgraph.graph import StateGraph, START, END
from core.config import LLM_CONFIG, MEMORY_CONFIG, AGENTS_CONFIG
from graph.state import GraphState
from graph.nodes import (
    pre_process, router, handle_out_of_domain,
    handle_transfer_human, post_process,
    llm as base_llm
)
from memory import get_checkpointer
from tools import build_tools
from agents import build_all_agents


def build_graph():
    # 建立工具 dict 與 agent 子圖
    tools_dict = build_tools()
    agent_subgraphs = build_all_agents(AGENTS_CONFIG, tools_dict, base_llm)

    # 路由函數：根據 next_agent 決定下一個節點
    def route_by_intent(state: GraphState):
        next_agent = state.get("next_agent", "")
        if next_agent == "out_of_domain":
            return "out_of_domain"
        if next_agent == "human":
            return "human"
        if next_agent in agent_subgraphs:
            return next_agent
        # fallback 到第一個 agent
        return list(agent_subgraphs.keys())[0] if agent_subgraphs else "out_of_domain"

    # 組裝 StateGraph
    workflow = StateGraph(GraphState)

    # 節點
    workflow.add_node("pre_process", pre_process)
    workflow.add_node("router", router)
    workflow.add_node("out_of_domain", handle_out_of_domain)
    workflow.add_node("human", handle_transfer_human)
    workflow.add_node("post_process", post_process)

    for name, subgraph in agent_subgraphs.items():
        workflow.add_node(name, subgraph)

    # 連線
    workflow.add_edge(START, "pre_process")
    workflow.add_edge("pre_process", "router")

    # router → 各 agent / out_of_domain / human
    route_map = {name: name for name in agent_subgraphs}
    route_map["out_of_domain"] = "out_of_domain"
    route_map["human"] = "human"
    workflow.add_conditional_edges("router", route_by_intent, route_map)

    # 各 agent → post_process（直接連接，不經 check_result）
    for name in agent_subgraphs:
        workflow.add_edge(name, "post_process")

    # out_of_domain → post_process
    workflow.add_edge("out_of_domain", "post_process")
    # human → post_process
    workflow.add_edge("human", "post_process")
    # post_process → END
    workflow.add_edge("post_process", END)

    # Checkpointer
    memory = get_checkpointer(MEMORY_CONFIG)

    return workflow.compile(checkpointer=memory)


app = build_graph()
