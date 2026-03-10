from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
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

    # 路由函數：根據 next_agents 用 Send() 實現 fan-out
    def route_by_intent(state: GraphState):
        agents = state.get("next_agents", [])

        if not agents:
            return [Send("out_of_domain", state)]
        if agents == ["out_of_domain"]:
            return [Send("out_of_domain", state)]
        if agents == ["human"]:
            return [Send("human", state)]

        # 過濾出有效的 agent，無效的跳過
        valid = [a for a in agents if a in agent_subgraphs]
        if not valid:
            return [Send("out_of_domain", state)]

        return [Send(a, state) for a in valid]

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

    # router → 各 agent / out_of_domain / human（透過 Send() fan-out）
    workflow.add_conditional_edges("router", route_by_intent)

    # 各 agent → post_process
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
