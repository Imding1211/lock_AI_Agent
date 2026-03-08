from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from core.config import LLM_CONFIG, MEMORY_CONFIG
from graph.state import GraphState
from graph.nodes import pre_process, post_process, llm as base_llm
from memory import get_checkpointer
from tools import build_tools


def build_graph():
    # 建立工具與 bound LLM
    tools = build_tools()
    llm_with_tools = base_llm.bind_tools(tools)

    # 建立 agent_llm 節點函數
    async def agent_llm(state: GraphState):
        print("  [agent_llm] LLM 正在思考...")
        response = await llm_with_tools.ainvoke(state["messages"])
        print(f"  [agent_llm] 回應類型: {'tool_calls' if getattr(response, 'tool_calls', None) else 'text'}")
        return {"messages": [response], "history": ["agent_llm"]}

    # 建立 tool_node
    tool_node = ToolNode(tools)

    async def execute_tools(state: GraphState):
        print("  [tool_node] 正在執行工具呼叫...")
        result = await tool_node.ainvoke(state)
        return {"messages": result["messages"], "history": ["tool_node"]}

    # 路由函數：判斷是否需要繼續呼叫工具
    def should_continue(state: GraphState):
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
        return "post_process"

    # 組裝 StateGraph
    workflow = StateGraph(GraphState)

    workflow.add_node("pre_process", pre_process)
    workflow.add_node("agent_llm", agent_llm)
    workflow.add_node("tools", execute_tools)
    workflow.add_node("post_process", post_process)

    # 連線
    workflow.add_edge(START, "pre_process")
    workflow.add_edge("pre_process", "agent_llm")
    workflow.add_conditional_edges(
        "agent_llm",
        should_continue,
        {"tools": "tools", "post_process": "post_process"}
    )
    workflow.add_edge("tools", "agent_llm")
    workflow.add_edge("post_process", END)

    # Checkpointer
    memory = get_checkpointer(MEMORY_CONFIG)

    return workflow.compile(checkpointer=memory)


app = build_graph()
