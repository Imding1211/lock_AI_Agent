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

from core.config import LINE_BOT_CONFIG, TEMPLATES_CONFIG

# 模組層級狀態（由 init() 初始化）
_configuration = None


def init(access_token: str):
    """初始化 LINE Messaging API 設定，由 app.py startup 呼叫"""
    global _configuration
    _configuration = Configuration(access_token=access_token)


async def show_loading(user_id: str):
    """顯示 LINE Loading 動畫"""
    loading_time = LINE_BOT_CONFIG.get("loading_animation_time", 5)
    async with AsyncApiClient(_configuration) as api_client:
        line_bot_api = AsyncMessagingApi(api_client)
        try:
            await line_bot_api.show_loading_animation(
                ShowLoadingAnimationRequest(chatId=user_id, loadingSeconds=loading_time)
            )
        except Exception as e:
            print(f"[Warning] 顯示 Loading 動畫失敗: {e}")


async def send_response(user_id: str, reply_token: str, message_text: str, message_objects: list | None = None):
    """嘗試 Reply API，失敗則降級 Push API。
    若有 message_objects（LINE Message 物件列表）則優先使用，否則降級為純文字。
    """
    messages = message_objects if message_objects else [TextMessage(text=message_text)]

    async with AsyncApiClient(_configuration) as api_client:
        line_bot_api = AsyncMessagingApi(api_client)
        try:
            print("[Reply] 嘗試使用 Reply API 回覆...")
            await line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=messages,
                )
            )
            print("[Reply] 成功！(免費)")
        except ApiException as e:
            print(f"[Reply] 失敗 (Token可能已失效): {e.status} - 準備降級使用 Push API")
            fallback_prefix = TEMPLATES_CONFIG.get("push_fallback_prefix", "【系統通知】讓您久等了，以下是您的回覆：\n")
            # Push 降級：TextMessage 加前綴，FlexMessage 原樣保留
            push_messages = []
            for msg in messages:
                if isinstance(msg, TextMessage):
                    push_messages.append(TextMessage(text=fallback_prefix + msg.text))
                else:
                    push_messages.append(msg)
            print("[Push] 嘗試使用 Push API 推播...")
            await line_bot_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=push_messages,
                )
            )
            print("[Push] 成功！(花費額度)")
