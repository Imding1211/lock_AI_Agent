"""Debug message logger — 將 agent / head / tool 之間的訊息流寫入 temp/debug_messages.md"""

import os
from datetime import datetime

_log_file = None
TEMP_DIR = os.path.join(os.path.dirname(__file__), "..", "temp")


def init_debug_log():
    """初始化 debug log 檔案（覆寫模式）。"""
    global _log_file
    os.makedirs(TEMP_DIR, exist_ok=True)
    path = os.path.join(TEMP_DIR, "debug_messages.md")
    _log_file = open(path, "w", encoding="utf-8")
    _log_file.write(f"# Debug Message Log\n\n生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    _log_file.flush()


def close_debug_log():
    """關閉 debug log 檔案。"""
    global _log_file
    if _log_file:
        _log_file.close()
        _log_file = None


def _extract_content(msg) -> str:
    """從 message 物件提取文字內容。"""
    content = msg.content if hasattr(msg, "content") else str(msg)
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and "text" in p:
                parts.append(p["text"])
            elif isinstance(p, str):
                parts.append(p)
        return "\n".join(parts)
    return str(content)


def log_messages(tag: str, messages):
    """記錄一組 messages（如 head→agent 派發、agent_llm 輸入）。"""
    if not _log_file:
        return
    _log_file.write(f"---\n\n## {tag}\n\n")
    for i, msg in enumerate(messages):
        mt = getattr(msg, "type", "unknown")
        content = _extract_content(msg)
        _log_file.write(f"### [{i}] `{mt}`\n\n```\n{content}\n```\n\n")
    _log_file.flush()


def log_response(tag: str, response):
    """記錄 LLM 回傳（含 tool_calls 或純文字）。"""
    if not _log_file:
        return
    _log_file.write(f"---\n\n## {tag}\n\n")
    if getattr(response, "tool_calls", None):
        import json
        for tc in response.tool_calls:
            name = tc.get("name", "?")
            args = tc.get("args", {})
            _log_file.write(f"**Tool Call:** `{name}`\n\n```json\n{json.dumps(args, ensure_ascii=False, indent=2)}\n```\n\n")
    content = _extract_content(response)
    if content:
        _log_file.write(f"```\n{content}\n```\n\n")
    _log_file.flush()


def log_tool_results(tag: str, messages):
    """記錄 tool 執行結果。"""
    if not _log_file:
        return
    _log_file.write(f"---\n\n## {tag}\n\n")
    for msg in messages:
        if hasattr(msg, "type") and msg.type == "tool":
            name = getattr(msg, "name", "unknown")
            content = _extract_content(msg)
            _log_file.write(f"### Tool Result: `{name}`\n\n```\n{content}\n```\n\n")
    _log_file.flush()


def log_final_answer(tag: str, answer: str):
    """記錄 head 給使用者的最終回覆。"""
    if not _log_file:
        return
    _log_file.write(f"---\n\n## {tag}\n\n```\n{answer}\n```\n\n")
    _log_file.flush()
