import os
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException

from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from core.config import STORAGE_CONFIG, USER_PROFILE_CONFIG

from graph.builder import build_graph
from storage import get_storage, close_storage
from memory import close_checkpointer
from profiles import init_facts_db, close_facts_db

import core.line_bot as line_bot
import core.debounce as debounce

# 載入環境變數 (.env)
load_dotenv()
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

app = FastAPI()

# 設定 Line 的 Parser
parser = WebhookParser(LINE_CHANNEL_SECRET)

# 審計日誌（在 startup 事件中非同步初始化）
audit_storage = None

@app.on_event("startup")
async def startup_event():
    global audit_storage
    audit_storage = await get_storage(STORAGE_CONFIG)
    if USER_PROFILE_CONFIG.get("facts_enabled", False):
        await init_facts_db(USER_PROFILE_CONFIG)
    langgraph_app = await build_graph()

    line_bot.init(LINE_CHANNEL_ACCESS_TOKEN)
    debounce.init(langgraph_app, audit_storage)

    asyncio.create_task(debounce.cleanup_stale_buffers())

@app.on_event("shutdown")
async def shutdown_event():
    await close_facts_db()
    await close_storage()
    await close_checkpointer()

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

        print(f"[收到訊息] '{new_text}' (Token: {new_token})")

        # 審計日誌：即時記錄使用者原始訊息（debounce 之前）
        if audit_storage:
            try:
                await audit_storage.log_message(user_id, "user_raw", new_text)
            except Exception as e:
                print(f"[Audit] 記錄原始訊息失敗: {e}")

        await line_bot.show_loading(user_id)
        debounce.add_message_to_buffer(user_id, new_token, new_text)

    return "OK"
