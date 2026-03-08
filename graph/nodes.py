import re
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from core.config import (
    LLM_CONFIG, INTENTS_CONFIG, REQUIRED_SLOTS,
    SYSTEM_CONFIG, USER_PROFILE_CONFIG, MEMORY_CONFIG
)
from profiles import ProfileManager
from graph.state import GraphState
from llms import get_llm

llm = get_llm(LLM_CONFIG)
profile_manager = ProfileManager(USER_PROFILE_CONFIG)


def build_system_prompt(user_profile: str) -> str:
    """動態組裝系統提示詞"""
    domain = SYSTEM_CONFIG.get("domain", "電子鎖")

    profile_section = "新使用者，尚無歷史資料。"
    if user_profile:
        profile_section = user_profile

    slots_section = ""
    if REQUIRED_SLOTS:
        slots_lines = "\n".join([f"  - {k}: {v}" for k, v in REQUIRED_SLOTS.items()])
        slots_section = f"""
7. 進行故障排除前，必須確認以下設備資訊（若使用者背景中已有則直接使用，不必重複詢問）：
{slots_lines}
   如果使用者無法提供，仍可給予通用建議，但應提醒資訊不足可能影響準確度。"""

    # 從 intents config 取得意圖描述，供 LLM 理解業務範圍
    intent_descriptions = ""
    if INTENTS_CONFIG:
        lines = []
        for intent in INTENTS_CONFIG:
            label = intent.get("label", intent["name"])
            desc = intent.get("description", "")
            lines.append(f"  - {label}: {desc}")
        intent_descriptions = "\n".join(lines)

    return f"""你是一位專業、友善的「{domain}」客服助理。

## 使用者背景
{profile_section}

## 業務範圍
{intent_descriptions}

## 行為準則
1. 一律使用繁體中文回答。
2. 只回答與「{domain}」相關的問題。若使用者的問題明顯與「{domain}」完全無關（例如天氣、股票、美食），請禮貌拒絕並提醒你的服務範圍。
3. 嚴格根據工具回傳的資料來回答，不可編造資訊。
4. 若某個工具的回傳資料不足以回答，請嘗試使用其他工具。
5. 當所有工具都無法提供足夠資訊時，使用 transfer_to_human 工具轉接真人客服。
6. 使用者明確要求轉接真人時，直接使用 transfer_to_human 工具。{slots_section}

## 回覆風格
- 語氣親切自然，像真人對話。
- 條理分明，適當使用編號或分點說明。
- 回答要精確且簡潔，避免冗長。"""


async def pre_process(state: GraphState, config: RunnableConfig):
    """載入 user profile、將 question 轉為 HumanMessage、組裝 system prompt"""
    print("  [pre_process] 正在準備 Agent 輸入...")

    # 載入 user profile
    user_profile = ""
    if USER_PROFILE_CONFIG.get("enabled", False):
        cfg = config.get("configurable", {})
        user_id = cfg.get("user_id") or cfg.get("thread_id", "anonymous")
        user_profile = await profile_manager.load_profile(user_id)
        if user_profile:
            print(f"  [pre_process] 已載入 {user_id} 的輪廓 ({len(user_profile)} 字元)")
        else:
            print(f"  [pre_process] {user_id} 尚無歷史輪廓")

    # 組裝 system prompt
    system_prompt = build_system_prompt(user_profile)

    # 建立 messages：system + 歷史對話 + 當前問題
    messages = [SystemMessage(content=system_prompt)]

    # 加入歷史對話（來自 chat_history）
    past_dialogue = state.get("chat_history", [])

    # 話題轉換偵測：若啟用，在 system prompt 中已有指引，agent 會自行處理
    topic_shift_enabled = MEMORY_CONFIG.get("topic_shift_detection", False)
    if topic_shift_enabled and past_dialogue:
        history_text = "\n".join(past_dialogue)
        messages.append(SystemMessage(content=f"[先前的對話紀錄]\n{history_text}"))

    # 加入當前問題
    messages.append(HumanMessage(content=state["question"]))

    return {
        "messages": messages,
        "user_profile": user_profile,
        "history": ["pre_process"]
    }


async def agent_llm(state: GraphState):
    """呼叫 bind_tools 後的 LLM，回傳 AI message（可能包含 tool_calls）"""
    print("  [agent_llm] LLM 正在思考...")
    # llm_with_tools 在 builder.py 中透過 bind_tools 建立，這裡用 state 中的 messages 呼叫
    # 注意：此函數需要在 builder.py 中用 functools.partial 注入 bound_llm
    raise NotImplementedError("agent_llm should be created via create_agent_llm_node in builder.py")


async def post_process(state: GraphState, config: RunnableConfig):
    """從 agent 最終回覆提取 answer、更新 user profile"""
    print("  [post_process] 正在提取最終回覆並更新輪廓...")

    # 從 messages 中取得最後一個 AI message 作為 answer
    answer = ""
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "type") and msg.type == "ai" and msg.content and not getattr(msg, "tool_calls", None):
            content = msg.content
            # Gemini 可能回傳 list of parts，取出純文字
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
                answer = "\n".join(text_parts).strip()
            else:
                answer = str(content).strip()
            break

    if not answer:
        answer = "抱歉，系統沒有產生回覆。"

    print(f"  [post_process] 最終回覆: {answer[:80]}...")

    # 判斷是否為轉接真人（檢查 tool 呼叫歷史）
    is_transfer = False
    topic_resolved = False
    for msg in state.get("messages", []):
        if hasattr(msg, "type") and msg.type == "ai" and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if tc.get("name") == "transfer_to_human":
                    is_transfer = True
                    break

    # 轉接真人時，使用 tool 回傳的格式化文字作為 answer
    if is_transfer:
        topic_resolved = True
        for msg in reversed(state.get("messages", [])):
            if hasattr(msg, "type") and msg.type == "tool" and msg.name == "transfer_to_human":
                answer = msg.content
                break

    history_items = ["post_process"]
    if topic_resolved:
        history_items.append("topic_resolved")

    # 更新 user profile
    if USER_PROFILE_CONFIG.get("enabled", False) and answer:
        cfg = config.get("configurable", {})
        user_id = cfg.get("user_id") or cfg.get("thread_id", "anonymous")
        existing_profile = state.get("user_profile", "")
        question = state.get("question", "")

        update_llm = get_llm(LLM_CONFIG)
        prompt = f"""
    You are a user profile manager for a smart lock customer service system.
    Your task is to analyze the conversation and update the user's profile with any new personal information.

    [Existing User Profile]
    {existing_profile if existing_profile else "(empty - new user)"}

    [Latest Conversation]
    User: {question}
    AI: {answer}

    Instructions:
    1. Identify any NEW or CORRECTED personal information from the conversation, such as:
       - Device model or brand (設備型號、品牌)
       - Living environment (居住環境, e.g., apartment, house)
       - Address (聯絡地址 — full street address, keep the original text exactly)
       - Phone number (電話號碼 — keep the original format exactly, e.g., 0912-345-678)
       - Installation date (安裝日期)
       - Past issues or concerns (過去遇到的問題)
       - Preferences or special requirements (偏好或特殊需求)
    2. IMPORTANT: Always preserve address and phone number verbatim from the user's message. Do NOT omit, summarize, or paraphrase them.
    3. If the user CORRECTS or UPDATES previously recorded information, REPLACE the old value with the new one.
    4. Merge new information into the existing profile.
    5. Output the COMPLETE updated profile in Markdown format (Traditional Chinese).
    6. If there is NO new personal information to record, output the existing profile as-is.
    7. Do NOT include the conversation content itself, only extracted personal facts.
    8. Keep it concise and well-organized with headers.

    Output the updated profile in Markdown:
    """

        try:
            response = await update_llm.ainvoke(prompt)
            updated = response.content.strip()
            if updated and len(updated) >= 10:
                await profile_manager.save_profile(user_id, updated)
                print(f"  [post_process] 已更新 {user_id} 的輪廓")
        except Exception as e:
            print(f"  [post_process] 更新輪廓失敗: {e}")

    # 記錄對話歷史
    new_exchange = [
        f"User: {state['question']}",
        f"AI: {answer}"
    ]

    return {
        "answer": answer,
        "history": history_items,
        "chat_history": new_exchange
    }
