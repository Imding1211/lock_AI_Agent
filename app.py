import os
import time
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException

# 引入 Line Bot SDK v3 相關套件
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    ShowLoadingAnimationRequest,
    ApiException
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from core.config import LINE_BOT_CONFIG, LLM_CONFIG, TEMPLATES_CONFIG, DEBOUNCE_CONFIG, INTENTS_CONFIG
from core.debounce import evaluate_completeness, calculate_debounce_wait, create_debounce_llm, llm_evaluate, generate_clarification_text

from graph.builder import app as langgraph_app

# 初始化防抖 LLM（使用 [llm] 的語言模型設定）
debounce_llm = create_debounce_llm(DEBOUNCE_CONFIG, LLM_CONFIG)

# 載入環境變數 (.env)
load_dotenv()
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

app = FastAPI()

# 設定 Line 的 Parser 與非同步 API 客戶端
parser = WebhookParser(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

# 訊息緩衝池：用來記錄每個使用者的狀態
user_buffers = {}

# LangGraph 執行超時（秒）
LANGGRAPH_TIMEOUT = 60

# Buffer TTL 設定
BUFFER_TTL_SECONDS = 300
BUFFER_CLEANUP_INTERVAL = 60

# 使用者 session 計數器：話題結束後遞增，產生新的 thread_id
user_sessions = {}  # {user_id: session_counter}

async def run_langgraph(user_id: str, user_text: str, pre_intent: str = None) -> tuple[str, list]:
    """將使用者訊息送入 LangGraph，並利用 user_id 維持對話記憶"""
    try:
        # 1. 設定對話的 Thread ID，讓 MemorySaver 知道這是哪位使用者的歷史紀錄
        #    thread_id 加上 session 後綴，話題結束後遞增以獲得乾淨的 chat_history
        session_id = user_sessions.get(user_id, 0)
        thread_id = f"{user_id}_{session_id}"
        config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id       # profile 用原始 user_id
            }
        }

        # 2. 建立輸入狀態 (只需傳入你的 state.py 定義好的 question)
        inputs = {
            "question": user_text
        }
        if pre_intent:
            inputs["intent"] = pre_intent

        # 3. 記錄執行前的 history 長度，用於區分本次 run 新增的 history items
        prev_state = await langgraph_app.aget_state(config)
        prev_history_len = len(prev_state.values.get("history", [])) if prev_state.values else 0

        # 4. 使用非同步呼叫 (ainvoke) 執行圖表，加上 timeout 防止永遠 hang
        print(f"🧠 [LangGraph] 開始思考 user_id: {user_id} 的問題...")
        try:
            result_state = await asyncio.wait_for(
                langgraph_app.ainvoke(inputs, config=config),
                timeout=LANGGRAPH_TIMEOUT
            )
        except asyncio.TimeoutError:
            print(f"⏱️ [LangGraph 超時] {user_id} 的問題處理超過 {LANGGRAPH_TIMEOUT} 秒")
            return "不好意思，系統處理時間過長，請稍後再試一次。如果問題持續，建議轉接真人客服。", []

        # 5. 取出 answer，並只回傳本次 run 新增的 history items
        final_answer = result_state.get("answer", "抱歉，系統沒有產生回覆。")
        full_history = result_state.get("history", [])
        current_history = full_history[prev_history_len:]
        return final_answer, current_history

    except Exception as e:
        print(f"❌ [LangGraph 執行錯誤] {e}")
        return "不好意思，系統大腦剛剛稍微當機了一下，請稍後再試一次！", []

async def send_line_message(user_id: str, reply_token: str, message_text: str):
    """嘗試 Reply API，失敗則降級 Push API"""
    async with AsyncApiClient(configuration) as api_client:
        line_bot_api = AsyncMessagingApi(api_client)
        try:
            print("🟢 嘗試使用 Reply API 回覆...")
            await line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=message_text)]
                )
            )
            print("✅ Reply 成功！(免費)")
        except ApiException as e:
            print(f"⚠️ Reply 失敗 (Token可能已失效): {e.status} - 準備降級使用 Push API")
            fallback_prefix = TEMPLATES_CONFIG.get("push_fallback_prefix", "【系統通知】讓您久等了，以下是您的回覆：\n")
            print("🟡 嘗試使用 Push API 推播...")
            await line_bot_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=fallback_prefix + message_text)]
                )
            )
            print("✅ Push 成功！(花費額度)")


async def langgraph_and_reply(user_id: str, reply_token: str, text: str, pre_intent: str = None) -> tuple[bool, bool]:
    """執行 LangGraph 並回覆使用者，回傳 (是否需要後續 slot 追問, 話題是否已結束)"""
    print(f"\n🚀 [開始處理] 準備將 '{text}' 送入 LangGraph...")
    ai_response, history = await run_langgraph(user_id, text, pre_intent=pre_intent)
    print(f"🧠 [LangGraph] 思考完畢！準備回傳...")
    await send_line_message(user_id, reply_token, ai_response)
    needs_followup = "ask_missing_slots" in history
    topic_resolved = "topic_resolved" in history
    return needs_followup, topic_resolved


async def process_and_reply(user_id: str, reply_token: str):
    """背景執行：等待防抖 -> 執行 LangGraph -> 嘗試 Reply -> 失敗則 Push"""
    try:
        min_wait = DEBOUNCE_CONFIG.get("min_wait", 1.5)
        max_wait = DEBOUNCE_CONFIG.get("max_wait", 5.0)
        threshold = DEBOUNCE_CONFIG.get("completeness_threshold", 0.5)

        # Phase 1: 並行執行 min_wait sleep + LLM 評估
        combined_text = "\n".join(user_buffers[user_id]["text"])
        sleep_task = asyncio.create_task(asyncio.sleep(min_wait))

        if debounce_llm:
            llm_task = asyncio.create_task(llm_evaluate(combined_text, INTENTS_CONFIG, debounce_llm))
        else:
            llm_task = None

        await sleep_task

        if llm_task:
            result = await llm_task
        else:
            result = {"completeness": evaluate_completeness(combined_text), "intent": None}

        score = result["completeness"]
        pre_intent = result.get("intent")

        # Phase 2: 不完整 → 反問使用者意圖，等待補充
        if score < threshold:
            print(f"[Debounce] text='{combined_text}' score={score:.2f} intent={pre_intent} → 反問意圖")
            clarification = generate_clarification_text(INTENTS_CONFIG)
            await send_line_message(user_id, reply_token, clarification)
            user_buffers[user_id]["awaiting_clarification"] = True
            return
        else:
            print(f"[Debounce] text='{combined_text}' score={score:.2f} intent={pre_intent} wait={min_wait}s")

        # Phase 3: 帶著 pre_intent 進 LangGraph
        needs_followup, topic_resolved = await langgraph_and_reply(user_id, reply_token, combined_text, pre_intent)
        if needs_followup and user_id in user_buffers:
            user_buffers[user_id]["awaiting_clarification"] = True
        if topic_resolved:
            user_sessions[user_id] = user_sessions.get(user_id, 0) + 1
            print(f"  [Session] {user_id} 話題已結束，session 遞增為 {user_sessions[user_id]}")

    except asyncio.CancelledError:
        print(f" ⏳ [任務取消] {user_id} 仍在輸入，更新計時器...")
        raise
        
    finally:
        # 清理緩衝池（等待反問回覆時不清理，保留累積的訊息）
        if user_id in user_buffers and user_buffers[user_id].get("task") == asyncio.current_task():
            if not user_buffers[user_id].get("awaiting_clarification"):
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

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_stale_buffers())

@app.post("/webhook")
async def line_webhook(request: Request):
    """接收 Line 官方傳來的 Webhook"""
    signature = request.headers.get('X-Line-Signature', '')
    body = await request.body()
    body_str = body.decode('utf-8')

    try:
        events = parser.parse(body_str, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature. Check your channel secret.")

    for event in events:
        # 我們目前只處理文字訊息
        if not isinstance(event, MessageEvent) or not isinstance(event.message, TextMessageContent):
            continue

        user_id = event.source.user_id
        new_text = event.message.text
        new_token = event.reply_token
        
        print(f"[📥 收到訊息] '{new_text}' (Token: {new_token})")

        loading_time = LINE_BOT_CONFIG.get("loading_animation_time", 5)
        async with AsyncApiClient(configuration) as api_client:
            line_bot_api = AsyncMessagingApi(api_client)
            # 使用 try-except 避免萬一動畫 API 呼叫失敗影響主流程
            try:
                await line_bot_api.show_loading_animation(
                    ShowLoadingAnimationRequest(chatId=user_id, loadingSeconds=loading_time)
                )
            except Exception as e:
                print(f"⚠️ 顯示 Loading 動畫失敗: {e}")

        # 防抖核心邏輯
        if user_id in user_buffers:
            if user_buffers[user_id].get("awaiting_clarification"):
                # 使用者回覆了反問 → 合併後直接送 LangGraph（跳過防抖）
                print(f"[Debounce] 收到反問回覆，合併後直送 LangGraph")
                user_buffers[user_id]["text"].append(new_text)
                user_buffers[user_id]["reply_token"] = new_token
                user_buffers[user_id]["awaiting_clarification"] = False
                user_buffers[user_id]["created_at"] = time.monotonic()
                combined = "\n".join(user_buffers[user_id]["text"])

                async def clarification_followup(uid, token, text):
                    try:
                        needs_followup, topic_resolved = await langgraph_and_reply(uid, token, text)
                        if needs_followup and uid in user_buffers:
                            user_buffers[uid]["awaiting_clarification"] = True
                        if topic_resolved:
                            user_sessions[uid] = user_sessions.get(uid, 0) + 1
                            print(f"  [Session] {uid} 話題已結束，session 遞增為 {user_sessions[uid]}")
                    finally:
                        if uid in user_buffers and user_buffers[uid].get("task") == asyncio.current_task():
                            if not user_buffers[uid].get("awaiting_clarification"):
                                del user_buffers[uid]

                new_task = asyncio.create_task(
                    clarification_followup(user_id, new_token, combined)
                )
                user_buffers[user_id]["task"] = new_task
                continue

            user_buffers[user_id]["task"].cancel()
            user_buffers[user_id]["text"].append(new_text)
            user_buffers[user_id]["reply_token"] = new_token
            user_buffers[user_id]["created_at"] = time.monotonic()
        else:
            user_buffers[user_id] = {
                "text": [new_text],
                "reply_token": new_token,
                "created_at": time.monotonic()
            }

        new_task = asyncio.create_task(
            process_and_reply(user_id, user_buffers[user_id]["reply_token"])
        )
        user_buffers[user_id]["task"] = new_task

    return "OK"