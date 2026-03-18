import time
import asyncio

from core.config import DEBOUNCE_CONFIG, SYSTEM_CONFIG, TEMPLATES_CONFIG
import core.line_bot as line_bot

# 模組層級狀態（由 init() 初始化）
_langgraph_app = None
_audit_storage = None

# 訊息緩衝池：用來記錄每個使用者的狀態
user_buffers = {}

# 從 config 讀取設定
LANGGRAPH_TIMEOUT = SYSTEM_CONFIG.get("request_timeout", 60)
BUFFER_TTL_SECONDS = DEBOUNCE_CONFIG.get("buffer_ttl", 300)
BUFFER_CLEANUP_INTERVAL = DEBOUNCE_CONFIG.get("cleanup_interval", 60)


def init(langgraph_app, audit_storage):
    """注入依賴，由 app.py startup 呼叫"""
    global _langgraph_app, _audit_storage
    _langgraph_app = langgraph_app
    _audit_storage = audit_storage


async def run_langgraph(user_id: str, user_text: str) -> tuple[str, list, list]:
    """將使用者訊息送入 LangGraph，並利用 user_id 維持對話記憶。
    回傳 (answer, history, response_ui)。
    """
    try:
        thread_prefix = SYSTEM_CONFIG.get("thread_prefix", "smart_lock_")
        thread_id = f"{thread_prefix}{user_id}"
        config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id
            }
        }

        inputs = {
            "question": user_text
        }

        prev_state = await _langgraph_app.aget_state(config)
        prev_history_len = len(prev_state.values.get("history", [])) if prev_state.values else 0

        print(f"[LangGraph] 開始思考 user_id: {user_id} 的問題...")
        try:
            result_state = await asyncio.wait_for(
                _langgraph_app.ainvoke(inputs, config=config),
                timeout=LANGGRAPH_TIMEOUT
            )
        except asyncio.TimeoutError:
            print(f"[LangGraph 超時] {user_id} 的問題處理超過 {LANGGRAPH_TIMEOUT} 秒")
            return TEMPLATES_CONFIG.get("error_timeout", "不好意思，系統處理時間過長，請稍後再試一次。如果問題持續，建議轉接真人客服。"), [], []

        final_answer = result_state.get("answer", TEMPLATES_CONFIG.get("error_no_reply", "抱歉，系統沒有產生回覆。"))
        full_history = result_state.get("history", [])
        current_history = full_history[prev_history_len:]
        response_ui = result_state.get("response_ui", [])
        return final_answer, current_history, response_ui

    except Exception as e:
        print(f"[LangGraph 執行錯誤] {e}")
        return TEMPLATES_CONFIG.get("error_system", "不好意思，系統大腦剛剛稍微當機了一下，請稍後再試一次！"), [], []


async def langgraph_and_reply(user_id: str, reply_token: str, text: str):
    """執行 LangGraph 並回覆使用者"""
    print(f"\n[開始處理] 準備將 '{text}' 送入 LangGraph...")

    if _audit_storage:
        try:
            await _audit_storage.log_message(user_id, "user", text)
        except Exception as e:
            print(f"[Audit] 記錄使用者訊息失敗: {e}")

    ai_response, history, response_ui = await run_langgraph(user_id, text)
    print(f"[LangGraph] 思考完畢！準備回傳...")

    if _audit_storage:
        try:
            await _audit_storage.log_message(user_id, "ai", ai_response)
        except Exception as e:
            print(f"[Audit] 記錄 AI 回覆失敗: {e}")

    await line_bot.send_response(
        user_id, reply_token, ai_response,
        message_objects=response_ui if response_ui else None,
    )


async def process_and_reply(user_id: str, reply_token: str):
    """背景執行：等待緩衝 -> 執行 LangGraph -> 嘗試 Reply -> 失敗則 Push"""
    try:
        await asyncio.sleep(DEBOUNCE_CONFIG.get("buffer_wait", 1.5))
        combined_text = "\n".join(user_buffers[user_id]["text"])
        await langgraph_and_reply(user_id, reply_token, combined_text)

    except asyncio.CancelledError:
        print(f" ⏳ [任務取消] {user_id} 仍在輸入，更新計時器...")
        raise

    finally:
        if user_id in user_buffers and user_buffers[user_id].get("task") == asyncio.current_task():
            del user_buffers[user_id]


async def cleanup_stale_buffers():
    """定期清理過期的使用者緩衝區"""
    while True:
        await asyncio.sleep(BUFFER_CLEANUP_INTERVAL)
        now = time.monotonic()
        stale_users = [
            uid for uid, buf in user_buffers.items()
            if now - buf.get("created_at", 0) > BUFFER_TTL_SECONDS
        ]
        for uid in stale_users:
            buf = user_buffers.pop(uid, None)
            if buf:
                task = buf.get("task")
                if task and not task.done():
                    task.cancel()
                print(f"  [Buffer 清理] 移除 {uid} 的過期緩衝")


def add_message_to_buffer(user_id: str, reply_token: str, text: str):
    """將訊息加入緩衝池，建立/重設防抖計時器"""
    if user_id in user_buffers:
        user_buffers[user_id]["task"].cancel()
        user_buffers[user_id]["text"].append(text)
        user_buffers[user_id]["reply_token"] = reply_token
        user_buffers[user_id]["created_at"] = time.monotonic()
    else:
        user_buffers[user_id] = {
            "text": [text],
            "reply_token": reply_token,
            "created_at": time.monotonic()
        }

    new_task = asyncio.create_task(
        process_and_reply(user_id, user_buffers[user_id]["reply_token"])
    )
    user_buffers[user_id]["task"] = new_task
