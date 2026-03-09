import re
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from core.config import (
    LLM_CONFIG, INTENTS_CONFIG, REQUIRED_SLOTS,
    SYSTEM_CONFIG, USER_PROFILE_CONFIG, MEMORY_CONFIG, AGENTS_CONFIG
)
from profiles import ProfileManager
from graph.state import GraphState
from llms import get_llm
from agents import load_prompt_template

llm = get_llm(LLM_CONFIG)
profile_manager = ProfileManager(USER_PROFILE_CONFIG)


async def pre_process(state: GraphState, config: RunnableConfig):
    """載入 user profile、將 question 轉為 HumanMessage"""
    print("  [pre_process] 正在準備輸入...")

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

    # 建立 messages：歷史對話 + 當前問題
    messages = []

    # 加入歷史對話（來自 chat_history）
    past_dialogue = state.get("chat_history", [])
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


async def router(state: GraphState, config: RunnableConfig):
    """用 LLM 做意圖分類，回傳 next_agent"""
    print("  [router] 正在分類意圖...")

    domain = SYSTEM_CONFIG.get("domain", "電子鎖")
    tried_agents = state.get("tried_agents", [])

    # 建構意圖選項清單
    intent_lines = []
    for intent in INTENTS_CONFIG:
        name = intent["name"]
        label = intent.get("label", name)
        desc = intent.get("description", "")
        intent_lines.append(f'- "{name}": {label} — {desc}')
    intent_list = "\n".join(intent_lines)

    # 建構已嘗試 agent 的提示
    tried_agents_section = ""
    if tried_agents:
        # 找到 tried_agents 對應的 intent targets
        agent_to_intents = {}
        for intent in INTENTS_CONFIG:
            target = intent.get("target", "")
            if target in tried_agents:
                agent_to_intents.setdefault(target, []).append(intent["name"])
        avoided = ", ".join([f'"{i}"' for intents in agent_to_intents.values() for i in intents])
        if avoided:
            tried_agents_section = f"\n6. The following intents have already been tried and failed: {avoided}. Choose a DIFFERENT intent."

    # 載入 router prompt
    router_prompt = load_prompt_template(
        "agents/prompts/router.md",
        domain=domain,
        intent_list=intent_list,
        tried_agents_section=tried_agents_section,
    )

    # 取得使用者問題（從 messages 中找最後一個 HumanMessage）
    question = state.get("question", "")

    response = await llm.ainvoke([
        SystemMessage(content=router_prompt),
        HumanMessage(content=question),
    ])

    # 解析 LLM 回覆的意圖名稱
    intent_name = response.content.strip().strip('"').strip("'").lower()
    print(f"  [router] 意圖分類結果: {intent_name}")

    # 從 intents 找到對應的 target (agent name)
    target = None
    for intent in INTENTS_CONFIG:
        if intent["name"] == intent_name:
            target = intent.get("target", intent_name)
            break

    if not target:
        # fallback: 如果 LLM 輸出不在預設意圖中，嘗試直接作為 agent name
        valid_agents = {a["name"] for a in AGENTS_CONFIG}
        if intent_name in valid_agents:
            target = intent_name
        else:
            target = "product_expert"  # 預設 fallback
            print(f"  [router] 未知意圖 '{intent_name}'，fallback 到 product_expert")

    return {
        "next_agent": target,
        "history": [f"router:{target}"]
    }


async def handle_out_of_domain(state: GraphState):
    """禮貌拒絕非業務問題"""
    print("  [out_of_domain] 禮貌拒絕...")
    domain = SYSTEM_CONFIG.get("domain", "電子鎖")
    answer = f"不好意思，我是「{domain}」的專屬客服助理，這個問題不在我的服務範圍內。如果您有任何關於{domain}的問題，我很樂意為您服務！"
    return {
        "answer": answer,
        "history": ["out_of_domain"]
    }


async def handle_transfer_human(state: GraphState, config: RunnableConfig):
    """轉接真人客服"""
    print("  [transfer_human] 正在準備轉接...")
    cfg = config.get("configurable", {})
    user_id = cfg.get("user_id") or cfg.get("thread_id", "anonymous")

    user_profile = await profile_manager.load_profile(user_id)

    phone = ""
    address = ""
    brand_model = ""
    if user_profile:
        phone_match = re.search(r'09\d{2}[\-\s]?\d{3}[\-\s]?\d{3}', user_profile)
        if phone_match:
            phone = phone_match.group()
        addr_match = re.search(
            r'[\u4e00-\u9fff]*(?:市|縣)[\u4e00-\u9fff]*(?:區|鄉|鎮|市)[\u4e00-\u9fff\d\s\-]*(?:路|街|巷|弄|號|樓)[\u4e00-\u9fff\d\s\-]*',
            user_profile
        )
        if addr_match:
            address = addr_match.group().strip()

    has_info = any([brand_model, phone, address])
    if has_info:
        header = "您好\n麻煩您確認並補充以下資訊"
    else:
        header = "您好\n麻煩您留下以下資訊"

    answer = (
        f"{header}\n"
        f"聯絡地址：{address}\n"
        f"電話：{phone}\n"
        f"設備品牌型號：{brand_model}\n"
        f"安裝日期：\n"
        f"另外再麻煩您錄影整個狀況的影片將其上傳，謝謝您"
    )

    return {
        "answer": answer,
        "history": ["transfer_human", "topic_resolved"]
    }


async def check_agent_result(state: GraphState):
    """檢查 agent 回覆是否充足，決定繼續或 fallback"""
    print("  [check_result] 正在評估回覆品質...")

    # 從 messages 取得最後一個 AI text message
    answer_text = ""
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "type") and msg.type == "ai" and msg.content and not getattr(msg, "tool_calls", None):
            content = msg.content
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
                answer_text = "\n".join(text_parts).strip()
            else:
                answer_text = str(content).strip()
            break

    # 檢查是否有 transfer_to_human 工具呼叫
    for msg in state.get("messages", []):
        if hasattr(msg, "type") and msg.type == "ai" and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if tc.get("name") == "transfer_to_human":
                    print("  [check_result] 偵測到轉接真人，標記為充足")
                    return {"history": ["check_result:sufficient"]}

    # 用 LLM 評估回覆是否充足
    insufficient_indicators = [
        "無法找到", "找不到相關", "沒有找到", "無法提供",
        "不足以回答", "沒有相關資料", "無相關資料",
    ]
    is_insufficient = any(indicator in answer_text for indicator in insufficient_indicators)

    if is_insufficient:
        tried = state.get("tried_agents", [])
        current_agent = state.get("next_agent", "")
        all_agents = {a["name"] for a in AGENTS_CONFIG}
        remaining = all_agents - set(tried) - {current_agent}

        if remaining:
            print(f"  [check_result] 回覆不足，嘗試 fallback（剩餘: {remaining}）")
            return {
                "next_agent": "__fallback__",
                "tried_agents": [current_agent],
                "history": ["check_result:fallback"]
            }
        else:
            print("  [check_result] 所有 agent 已嘗試，轉接真人")
            return {
                "next_agent": "__transfer_human__",
                "tried_agents": [current_agent],
                "history": ["check_result:all_exhausted"]
            }

    print("  [check_result] 回覆充足")
    return {"history": ["check_result:sufficient"]}


async def post_process(state: GraphState, config: RunnableConfig):
    """從 agent 最終回覆提取 answer、更新 user profile"""
    print("  [post_process] 正在提取最終回覆並更新輪廓...")

    # 如果 answer 已經被設定（例如 out_of_domain 或 transfer_human），直接使用
    existing_answer = state.get("answer", "")
    if existing_answer:
        answer = existing_answer
    else:
        # 從 messages 中取得最後一個 AI message 作為 answer
        answer = ""
        for msg in reversed(state.get("messages", [])):
            if hasattr(msg, "type") and msg.type == "ai" and msg.content and not getattr(msg, "tool_calls", None):
                content = msg.content
                if isinstance(content, list):
                    text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
                    answer = "\n".join(text_parts).strip()
                else:
                    answer = str(content).strip()
                break

    if not answer:
        answer = "抱歉，系統沒有產生回覆。"

    print(f"  [post_process] 最終回覆: {answer[:80]}...")

    # 判斷是否為轉接真人（檢查 history）
    topic_resolved = False
    if "topic_resolved" in state.get("history", []):
        topic_resolved = True

    # 也檢查 tool 呼叫歷史
    if not topic_resolved:
        for msg in state.get("messages", []):
            if hasattr(msg, "type") and msg.type == "ai" and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    if tc.get("name") == "transfer_to_human":
                        topic_resolved = True
                        # 使用 tool 回傳的格式化文字作為 answer
                        for rmsg in reversed(state.get("messages", [])):
                            if hasattr(rmsg, "type") and rmsg.type == "tool" and rmsg.name == "transfer_to_human":
                                answer = rmsg.content
                                break
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
