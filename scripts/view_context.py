"""CLI 工具：從 checkpointer 撈出完整 messages 上下文，輸出為 .md 檔。

用法：
    python scripts/view_context.py <thread_id>
"""

import asyncio
import os
import sys
from datetime import datetime

# 讓 import 能找到專案根目錄
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TYPE_EMOJI = {
    "system": "🤖",
    "human": "🧑",
    "ai": "🧠",
    "tool": "🔧",
}

TEMP_DIR = os.path.join(os.path.dirname(__file__), "..", "temp")
OUTPUT_PATH = os.path.join(TEMP_DIR, "messages_context.md")


def _format_content(content) -> str:
    """將 msg.content (str | list) 轉為純文字。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _build_agent_prompts(user_profile: str) -> dict[str, str]:
    """重建每個 agent 的 system prompt，回傳 {agent_name: prompt_text}。"""
    from core.config import AGENTS_CONFIG, SYSTEM_CONFIG
    from agents import load_prompt_template, _build_slots_section

    domain = SYSTEM_CONFIG.get("domain", "電子鎖")
    slots_section = _build_slots_section()
    profile_section = user_profile if user_profile else "新使用者，尚無歷史資料。"

    prompts = {}
    for agent_config in AGENTS_CONFIG:
        name = agent_config["name"]
        prompt_file = agent_config["prompt_file"]
        try:
            prompt = load_prompt_template(
                prompt_file,
                domain=domain,
                user_profile=profile_section,
                slots_section=slots_section,
            )
            prompts[name] = prompt
        except Exception as e:
            prompts[name] = f"（載入失敗: {e}）"
    return prompts


async def main(thread_id: str):
    from graph.builder import build_graph
    from memory import close_checkpointer

    app = await build_graph()

    config = {"configurable": {"thread_id": thread_id, "user_id": thread_id}}
    state_snapshot = await app.aget_state(config)

    if not state_snapshot or not state_snapshot.values:
        print(f"找不到 thread_id={thread_id} 的狀態資料。")
        await close_checkpointer()
        return

    values = state_snapshot.values
    messages = values.get("messages", [])
    summary = values.get("summary", "")
    history = values.get("history", [])
    user_profile = values.get("user_profile", "")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    lines.append("# 📋 Messages 上下文記錄\n")
    lines.append(f"> 🧵 Thread: `{thread_id}`")
    lines.append(f"> 🕐 {timestamp}")
    lines.append(f"> 💬 共 {len(messages)} 則 messages\n")
    lines.append("---\n")

    # Summary
    lines.append("## 📝 摘要 (Summary)\n")
    if summary:
        lines.append(f"> {summary}\n")
    else:
        lines.append("> (無摘要)\n")
    lines.append("---\n")

    # History
    lines.append("## 🗂️ 執行路徑 (History)\n")
    if history:
        lines.append("`" + "` → `".join(history) + "`\n")
    else:
        lines.append("(無路徑記錄)\n")
    lines.append("---\n")

    # System Prompt（各 agent）
    lines.append("## 🎯 System Prompt\n")
    agent_prompts = _build_agent_prompts(user_profile)
    for agent_name, prompt in agent_prompts.items():
        lines.append(f"### 🤖 `{agent_name}`\n")
        lines.append(f"```\n{prompt}\n```\n")
    lines.append("---\n")

    # Checkpoint Messages
    lines.append("## 💬 Checkpoint Messages\n")
    if not messages:
        lines.append("(無 messages)\n")
    for i, msg in enumerate(messages):
        msg_type = getattr(msg, "type", "unknown")
        emoji = TYPE_EMOJI.get(msg_type, "📨")
        content = _format_content(msg.content) if hasattr(msg, "content") else str(msg)

        lines.append(f"### {emoji} [{i}] `{msg_type}`\n")
        lines.append(f"```\n{content}\n```\n")

    # 寫入檔案
    os.makedirs(TEMP_DIR, exist_ok=True)
    output = "\n".join(lines)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"已輸出至 {OUTPUT_PATH}（{len(messages)} 則 checkpoint messages）")

    await close_checkpointer()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/view_context.py <thread_id>")
        sys.exit(1)

    thread_id = sys.argv[1]
    asyncio.run(main(thread_id))
