import json
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage
from langchain_core.tools import StructuredTool
from graph.state import GraphState
from core.config import SYSTEM_CONFIG, REQUIRED_SLOTS
from tools.pgvector_store import UI_METADATA_DELIMITER


def load_prompt_template(prompt_file: str, **kwargs) -> str:
    """讀取 .md 提示詞模板並填入變數"""
    with open(prompt_file, "r", encoding="utf-8") as f:
        template = f.read()
    return template.format(**kwargs)


def _build_slots_section() -> str:
    """從 REQUIRED_SLOTS 建構 slots 提示段落"""
    if not REQUIRED_SLOTS:
        return ""
    slots_lines = "\n".join([f"  - {k}: {v}" for k, v in REQUIRED_SLOTS.items()])
    return f"""
7. 進行故障排除前，必須確認以下設備資訊（若使用者背景中已有則直接使用，不必重複詢問）：
{slots_lines}
   如果使用者無法提供，仍可給予通用建議，但應提醒資訊不足可能影響準確度。"""


def build_agent_executor(agent_config: dict, tools_dict: dict[str, StructuredTool], llm, ui_type_map: dict[str, str] | None = None):
    """為單一 agent 建構可呼叫的 subgraph（agent_llm ↔ tool_node 迴圈）"""
    agent_name = agent_config["name"]
    prompt_file = agent_config["prompt_file"]
    tool_names = agent_config.get("tools", [])
    _ui_type_map = ui_type_map or {}

    # 收集此 agent 使用的工具
    agent_tools = [tools_dict[name] for name in tool_names if name in tools_dict]

    # 綁定工具到 LLM（無工具時跳過綁定）
    if agent_tools:
        llm_with_tools = llm.bind_tools(agent_tools)
        llm_force_tool = llm.bind_tools(agent_tools, tool_choice="any")
    else:
        llm_with_tools = llm
        llm_force_tool = llm

    # 建構 subgraph
    def build_subgraph():
        async def agent_llm_node(state: GraphState):
            print(f"  [{agent_name}:agent_llm] LLM 正在思考...")

            # 動態組裝 system prompt
            domain = SYSTEM_CONFIG.get("domain", "電子鎖")
            user_profile = state.get("user_profile", "")
            profile_section = user_profile if user_profile else "新使用者，尚無歷史資料。"
            slots_section = _build_slots_section()

            system_prompt = load_prompt_template(
                prompt_file,
                domain=domain,
                user_profile=profile_section,
                slots_section=slots_section,
            )

            # 將 system prompt 注入到 messages 最前面
            messages = [SystemMessage(content=system_prompt)] + list(state.get("messages", []))

            # 無工具時直接使用 LLM；有工具時首次強制使用工具
            if not agent_tools:
                active_llm = llm_with_tools
            else:
                has_tool_result = any(
                    hasattr(m, "type") and m.type == "tool"
                    for m in state.get("messages", [])
                )
                active_llm = llm_with_tools if has_tool_result else llm_force_tool

            response = await active_llm.ainvoke(messages)
            print(f"  [{agent_name}:agent_llm] 回應類型: {'tool_calls' if getattr(response, 'tool_calls', None) else 'text'}")
            return {"messages": [response], "history": [f"{agent_name}:agent_llm"]}

        tool_node = ToolNode(agent_tools)

        async def execute_tools(state: GraphState):
            print(f"  [{agent_name}:tool_node] 正在執行工具呼叫...")
            result = await tool_node.ainvoke(state)

            # 攔截 metadata：從 ToolMessage 中剝離 UI_METADATA，寫入 ui_hints
            ui_hints = []
            for msg in result["messages"]:
                if not (hasattr(msg, "type") and msg.type == "tool"):
                    continue
                tool_name = getattr(msg, "name", "")
                if _ui_type_map.get(tool_name, "TEXT") == "TEXT":
                    continue
                if not (isinstance(msg.content, str) and UI_METADATA_DELIMITER in msg.content):
                    continue
                clean_text, raw_meta = msg.content.split(UI_METADATA_DELIMITER, 1)
                msg.content = clean_text  # LLM 只看乾淨文字
                try:
                    meta = json.loads(raw_meta)
                    ui_hints.append(meta)
                except json.JSONDecodeError:
                    print(f"  [{agent_name}:tool_node] UI metadata JSON 解析失敗，跳過")

            return {
                "messages": result["messages"],
                "ui_hints": ui_hints,
                "history": [f"{agent_name}:tool_node"],
            }

        def should_continue(state: GraphState):
            last_message = state["messages"][-1]
            if getattr(last_message, "tool_calls", None):
                return "tools"
            return END

        workflow = StateGraph(GraphState)
        workflow.add_node("agent_llm", agent_llm_node)
        workflow.add_node("tools", execute_tools)

        workflow.add_edge(START, "agent_llm")
        workflow.add_conditional_edges(
            "agent_llm",
            should_continue,
            {"tools": "tools", END: END}
        )
        workflow.add_edge("tools", "agent_llm")

        return workflow.compile()

    return build_subgraph()


def build_all_agents(agents_config: list, tools_dict: dict[str, StructuredTool], llm, ui_type_map: dict[str, str] | None = None) -> dict:
    """建構所有 agent 子圖，回傳 dict[str, CompiledGraph]"""
    agents = {}
    for agent_config in agents_config:
        name = agent_config["name"]
        subgraph = build_agent_executor(agent_config, tools_dict, llm, ui_type_map=ui_type_map)
        agents[name] = subgraph
        print(f"[*] 已建構 Agent: {name} — {agent_config.get('label', '')}")
    return agents
