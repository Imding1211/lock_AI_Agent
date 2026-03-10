from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from core.config import (
    LLM_CONFIG, INTENTS_CONFIG,
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
        "answer": "",
        "history": ["pre_process"]
    }


async def router(state: GraphState, config: RunnableConfig):
    """用 LLM 做意圖分類，回傳 next_agents（支援多意圖）"""
    print("  [router] 正在分類意圖...")

    domain = SYSTEM_CONFIG.get("domain", "電子鎖")

    # 建構意圖選項清單
    intent_lines = []
    for intent in INTENTS_CONFIG:
        name = intent["name"]
        label = intent.get("label", name)
        desc = intent.get("description", "")
        intent_lines.append(f'- "{name}": {label} — {desc}')
    intent_list = "\n".join(intent_lines)

    # 載入 router prompt
    router_prompt = load_prompt_template(
        "agents/prompts/router.md",
        domain=domain,
        intent_list=intent_list,
    )

    # 取得使用者問題（從 messages 中找最後一個 HumanMessage）
    question = state.get("question", "")

    response = await llm.ainvoke([
        SystemMessage(content=router_prompt),
        HumanMessage(content=question),
    ])

    # 解析 LLM 回覆（可能含多行意圖名稱）
    raw = response.content.strip()
    intent_names = [line.strip().strip('"').strip("'").lower() for line in raw.splitlines() if line.strip()]
    print(f"  [router] 意圖分類結果: {intent_names}")

    # 建構意圖名稱 → target 對應表
    intent_to_target = {}
    for intent in INTENTS_CONFIG:
        intent_to_target[intent["name"]] = intent.get("target", intent["name"])
    valid_agents = {a["name"] for a in AGENTS_CONFIG}

    # 逐一解析，去重
    targets = []
    seen = set()
    for intent_name in intent_names:
        if intent_name in intent_to_target:
            t = intent_to_target[intent_name]
        elif intent_name in valid_agents:
            t = intent_name
        else:
            print(f"  [router] 未知意圖 '{intent_name}'，跳過")
            continue
        if t not in seen:
            targets.append(t)
            seen.add(t)

    if not targets:
        targets = ["product_expert"]
        print("  [router] 無有效意圖，fallback 到 product_expert")

    # out_of_domain / human 不與其他意圖混合
    if "out_of_domain" in targets or "human" in targets:
        targets = [targets[0]]

    print(f"  [router] 派發目標: {targets}")

    return {
        "next_agent": targets[0],
        "next_agents": targets,
        "history": [f"router:{'+'.join(targets)}"]
    }


async def handle_out_of_domain(state: GraphState):
    """用 LLM 禮貌拒絕非業務問題"""
    print("  [out_of_domain] 用 LLM 生成禮貌拒絕...")
    domain = SYSTEM_CONFIG.get("domain", "電子鎖")
    question = state.get("question", "")
    prompt = f"你是「{domain}」專屬客服。使用者問了與服務範圍無關的問題：「{question}」。請用繁體中文禮貌拒絕並引導詢問{domain}相關問題。語氣親切簡潔。"
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    return {
        "answer": response.content.strip(),
        "history": ["out_of_domain"]
    }


async def handle_transfer_human(state: GraphState, config: RunnableConfig):
    """轉接真人客服"""
    print("  [transfer_human] 正在準備轉接...")
    cfg = config.get("configurable", {})
    user_id = cfg.get("user_id") or cfg.get("thread_id", "anonymous")

    user_profile = await profile_manager.load_profile(user_id)

    import re
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


async def merge_answers(state: GraphState):
    """從 agent 回覆提取 answer（多 agent 用 LLM 合併）+ 偵測 topic_resolved"""
    print("  [merge_answers] 正在提取並合併回覆...")

    # 如果 answer 已經被設定（例如 out_of_domain 或 transfer_human），直接使用
    existing_answer = state.get("answer", "")
    if existing_answer:
        answer = existing_answer
    else:
        # 根據 next_agents 數量決定提取邏輯
        agents_dispatched = state.get("next_agents", [])
        num_agents = len(agents_dispatched)

        if num_agents <= 1:
            # 單一 agent：取最後一個 AI message
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
        else:
            # 多 agent：收集所有 final AI messages（非 tool_call），用 LLM 合併
            ai_answers = []
            for msg in state.get("messages", []):
                if hasattr(msg, "type") and msg.type == "ai" and msg.content and not getattr(msg, "tool_calls", None):
                    content = msg.content
                    if isinstance(content, list):
                        text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
                        text = "\n".join(text_parts).strip()
                    else:
                        text = str(content).strip()
                    if text:
                        ai_answers.append(text)

            if len(ai_answers) <= 1:
                answer = ai_answers[0] if ai_answers else ""
            else:
                # 用 LLM 合併多段回覆
                print(f"  [merge_answers] 合併 {len(ai_answers)} 段 agent 回覆...")
                domain = SYSTEM_CONFIG.get("domain", "電子鎖")
                merge_prompt = load_prompt_template(
                    "agents/prompts/merge_answers.md",
                    domain=domain,
                )
                parts = "\n\n---\n\n".join([f"【回覆 {i+1}】\n{a}" for i, a in enumerate(ai_answers)])
                merge_response = await llm.ainvoke([
                    HumanMessage(content=f"{merge_prompt}\n\n{parts}")
                ])
                answer = merge_response.content.strip()

    if not answer:
        answer = "抱歉，系統沒有產生回覆。"

    print(f"  [merge_answers] 最終回覆: {answer[:10]}...")

    # 判斷是否為轉接真人（檢查 history 和 tool 呼叫）
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

    history_items = ["merge_answers"]
    if topic_resolved:
        history_items.append("topic_resolved")

    return {
        "answer": answer,
        "history": history_items,
    }


async def update_profile(state: GraphState, config: RunnableConfig):
    """用 LLM 從對話萃取個資並更新 user profile"""
    print("  [update_profile] 正在更新使用者輪廓...")

    answer = state.get("answer", "")

    if USER_PROFILE_CONFIG.get("enabled", False) and answer:
        cfg = config.get("configurable", {})
        user_id = cfg.get("user_id") or cfg.get("thread_id", "anonymous")
        existing_profile = state.get("user_profile", "")
        question = state.get("question", "")
        domain = SYSTEM_CONFIG.get("domain", "電子鎖")

        prompt = load_prompt_template(
            "agents/prompts/update_profile.md",
            domain=domain,
            existing_profile=existing_profile if existing_profile else "(empty - new user)",
            question=question,
            answer=answer,
        )

        try:
            response = await llm.ainvoke(prompt)
            updated = response.content.strip()
            if updated and len(updated) >= 10:
                await profile_manager.save_profile(user_id, updated)
                print(f"  [update_profile] 已更新 {user_id} 的輪廓")
        except Exception as e:
            print(f"  [update_profile] 更新輪廓失敗: {e}")

    return {
        "history": ["update_profile"]
    }


async def post_process(state: GraphState):
    """記錄 chat_history 並回傳最終 answer"""
    print("  [post_process] 記錄對話歷史...")

    answer = state.get("answer", "")

    # 記錄對話歷史
    new_exchange = [
        f"User: {state['question']}",
        f"AI: {answer}"
    ]

    return {
        "answer": answer,
        "history": ["post_process"],
        "chat_history": new_exchange
    }
