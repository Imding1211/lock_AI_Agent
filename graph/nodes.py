import json
import re
from langchain_core.messages import HumanMessage, SystemMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from core.config import (
    LLM_CONFIG, INTENTS_CONFIG,
    SYSTEM_CONFIG, USER_PROFILE_CONFIG, MEMORY_CONFIG, AGENTS_CONFIG,
    PROMPTS_CONFIG, TEMPLATES_CONFIG,
)
from profiles import ProfileManager
from tools.transfer_human import TransferHumanTool
from tools.line_ui_factory import build_line_messages
from graph.state import GraphState
from llms import get_llm
from agents import load_prompt_template
from core.debug_log import log_final_answer as debug_log_final_answer

llm = get_llm(LLM_CONFIG)
profile_manager = ProfileManager(USER_PROFILE_CONFIG)
_transfer_tool = TransferHumanTool({})


async def pre_process(state: GraphState, config: RunnableConfig):
    """載入 user profile、將 question 轉為 HumanMessage"""
    print("  [pre_process] 正在準備輸入...")

    # 載入 user profile
    user_profile = ""
    if USER_PROFILE_CONFIG.get("enabled", False):
        cfg = config.get("configurable", {})
        user_id = cfg.get("user_id") or cfg.get("thread_id", "anonymous")
        user_profile = await profile_manager.load_full_profile(user_id)
        if user_profile:
            print(f"  [pre_process] 已載入 {user_id} 的輪廓 ({len(user_profile)} 字元)")
        else:
            print(f"  [pre_process] {user_id} 尚無歷史輪廓")

    # 建立 messages：摘要 + 當前問題
    messages = []

    # 加入對話摘要（來自 manage_memory 壓縮）
    summary = state.get("summary", "")
    if summary:
        messages.append(SystemMessage(content=(
            f"[前情提要]\n{summary}\n\n"
            "【注意】以上為歷史對話摘要，可能包含多個不同話題。"
            "請只參考與使用者「當前問題」直接相關的部分，"
            "忽略不相關的歷史話題，避免將不同主題的資訊混入回答。"
        )))

    # 加入當前問題
    messages.append(HumanMessage(content=state["question"]))

    return {
        "messages": messages,
        "user_profile": user_profile,
        "answer": "",
        "ui_hints": [],
        "response_ui": [],
        "history": ["pre_process"]
    }


async def manage_memory(state: GraphState, config: RunnableConfig):
    """語意摘要壓縮：當 messages 超過閾值時，用 LLM 摘要舊訊息並刪除"""
    print("  [manage_memory] 檢查是否需要壓縮記憶...")

    threshold = MEMORY_CONFIG.get("max_messages_threshold", 6)
    retention_pair = MEMORY_CONFIG.get("context_retention_pair", 1)
    messages = state.get("messages", [])

    if len(messages) <= threshold:
        print(f"  [manage_memory] 訊息數 {len(messages)} <= 閾值 {threshold}，跳過壓縮")
        return {"history": ["manage_memory:skip"]}

    # 計算要保留的最近訊息數量（每對 = 1 human + 1 ai）
    keep_count = retention_pair * 2
    messages_to_summarize = messages[:-keep_count] if keep_count > 0 else messages
    messages_to_keep = messages[-keep_count:] if keep_count > 0 else []

    # 格式化待摘要的訊息
    dialogue_lines = []
    for msg in messages_to_summarize:
        role = getattr(msg, "type", "unknown")
        content = msg.content if hasattr(msg, "content") else str(msg)
        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
            content = "\n".join(text_parts)
        if role == "human":
            dialogue_lines.append(f"使用者: {content}")
        elif role == "ai" and content:
            dialogue_lines.append(f"客服: {content}")
        elif role == "system":
            dialogue_lines.append(f"系統: {content}")

    if not dialogue_lines:
        return {"history": ["manage_memory:skip"]}

    dialogue_text = "\n".join(dialogue_lines)

    # 載入摘要 prompt 並呼叫 LLM
    existing_summary = state.get("summary", "")
    domain = SYSTEM_CONFIG.get("domain", "電子鎖")

    summarize_prompt = load_prompt_template(
        PROMPTS_CONFIG.get("summarizer", "agents/prompts/summarize_messages.md"),
        domain=domain,
        existing_summary=existing_summary if existing_summary else "(無既有摘要)",
    )

    response = await llm.ainvoke([
        SystemMessage(content=summarize_prompt),
        HumanMessage(content=dialogue_text),
    ])
    new_summary = response.content.strip()
    print(f"  [manage_memory] 已生成摘要 ({len(new_summary)} 字元)")

    # 產生 RemoveMessage 指令，刪除舊訊息
    remove_messages = [RemoveMessage(id=msg.id) for msg in messages_to_summarize if hasattr(msg, "id") and msg.id]

    print(f"  [manage_memory] 刪除 {len(remove_messages)} 條舊訊息，保留 {len(messages_to_keep)} 條")

    return {
        "summary": new_summary,
        "messages": remove_messages,
        "history": ["manage_memory:summarized"],
    }


async def rewrite_query(state: GraphState, config: RunnableConfig):
    """用 LLM 將口語化問題改寫為精準檢索句"""
    original = state.get("question", "")
    user_profile = state.get("user_profile", "")
    summary = state.get("summary", "")
    domain = SYSTEM_CONFIG.get("domain", "電子鎖")

    # 載入 prompt 並呼叫 LLM
    prompt = load_prompt_template(
        PROMPTS_CONFIG.get("rewriter", "agents/prompts/rewrite_query.md"),
        domain=domain,
        user_profile=user_profile or "(無使用者輪廓)",
        summary=summary or "(無前情提要)",
        question=original,
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        rewritten = response.content.strip()
        if not rewritten:
            rewritten = original
    except Exception as e:
        print(f"  [rewrite_query] 改寫失敗，使用原始問題: {e}")
        rewritten = original

    if rewritten != original:
        print(f"  [rewrite_query] 改寫: {original} → {rewritten}")
    else:
        print(f"  [rewrite_query] 問題無需改寫")

    return {
        "question": rewritten,
        "messages": [HumanMessage(content=rewritten)],
        "history": ["rewrite_query"],
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
        PROMPTS_CONFIG.get("router", "agents/prompts/router.md"),
        domain=domain,
        intent_list=intent_list,
    )

    # 取得使用者問題（從 messages 中找最後一個 HumanMessage）
    question = state.get("question", "")

    # Guardrail：敏感交易詞彙強制轉接真人
    sensitive_keywords = SYSTEM_CONFIG.get("sensitive_keywords", [])
    if sensitive_keywords:
        for kw in sensitive_keywords:
            if kw in question:
                print(f"  [Guardrail] 偵測到敏感詞彙「{kw}」，強制轉接真人")
                cfg = config.get("configurable", {})
                user_id = cfg.get("user_id") or cfg.get("thread_id", "anonymous")
                answer = await _transfer_tool.generate_form(user_id, extra_text=question)
                return {
                    "answer": answer,
                    "next_agents": [],
                    "history": ["guardrail_triggered", "topic_resolved"],
                }

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

    # transfer_human：由 router 直接產生轉接表單
    if targets == ["human"]:
        print("  [router] 直接處理 transfer_human...")
        cfg = config.get("configurable", {})
        user_id = cfg.get("user_id") or cfg.get("thread_id", "anonymous")
        answer = await _transfer_tool.generate_form(user_id, extra_text=question)
        return {
            "answer": answer,
            "next_agents": [],
            "history": ["router:transfer_human", "topic_resolved"],
        }

    # out_of_domain：由 router 直接產生禮貌拒絕
    if targets == ["out_of_domain"]:
        print("  [router] 直接處理 out_of_domain...")
        domain = SYSTEM_CONFIG.get("domain", "電子鎖")
        prompt = f"你是「{domain}」專屬客服。使用者問了與服務範圍無關的問題：「{question}」。請用繁體中文禮貌拒絕並引導詢問{domain}相關問題。語氣親切簡潔。"
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return {
            "answer": response.content.strip(),
            "next_agents": [],
            "history": ["router:out_of_domain"],
        }

    print(f"  [router] 派發目標: {targets}")

    return {
        "next_agents": targets,
        "history": [f"router:{'+'.join(targets)}"]
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
            # 多 agent：從尾端收集最近 N 個 AI messages（非 tool_call），避免舊保留訊息混入
            ai_answers = []
            for msg in reversed(state.get("messages", [])):
                if hasattr(msg, "type") and msg.type == "ai" and msg.content and not getattr(msg, "tool_calls", None):
                    content = msg.content
                    if isinstance(content, list):
                        text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
                        text = "\n".join(text_parts).strip()
                    else:
                        text = str(content).strip()
                    if text:
                        ai_answers.append(text)
                    if len(ai_answers) >= num_agents:
                        break
            ai_answers.reverse()

            if len(ai_answers) <= 1:
                answer = ai_answers[0] if ai_answers else ""
            else:
                # 用 LLM 合併多段回覆
                print(f"  [merge_answers] 合併 {len(ai_answers)} 段 agent 回覆...")
                domain = SYSTEM_CONFIG.get("domain", "電子鎖")
                merge_prompt = load_prompt_template(
                    PROMPTS_CONFIG.get("merger", "agents/prompts/merge_answers.md"),
                    domain=domain,
                )
                parts = "\n\n---\n\n".join([f"【回覆 {i+1}】\n{a}" for i, a in enumerate(ai_answers)])
                merge_response = await llm.ainvoke([
                    HumanMessage(content=f"{merge_prompt}\n\n{parts}")
                ])
                answer = merge_response.content.strip()

    if not answer:
        answer = TEMPLATES_CONFIG.get("error_no_reply", "抱歉，系統沒有產生回覆。")

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
                        # 將 Agent 的過場語氣與 Tool 回傳的表單合併
                        agent_apology = ""
                        form_content = ""
                        for rmsg in reversed(state.get("messages", [])):
                            if hasattr(rmsg, "type") and rmsg.type == "ai" and getattr(rmsg, "tool_calls", None):
                                content = rmsg.content
                                if isinstance(content, list):
                                    text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
                                    agent_apology = "\n".join(text_parts).strip()
                                else:
                                    agent_apology = str(content).strip()
                            elif hasattr(rmsg, "type") and rmsg.type == "tool" and rmsg.name == "transfer_to_human":
                                form_content = rmsg.content

                            if agent_apology and form_content:
                                break

                        # 組合最終回覆：如果有道歉語，就放在表單前面
                        if agent_apology:
                            answer = f"{agent_apology}\n\n{form_content}"
                        else:
                            answer = form_content
                        break

    # 清除 tool 相關的中間訊息，只保留對話脈絡（human / ai 純文字 / system）
    remove_messages = []
    for msg in state.get("messages", []):
        if not (hasattr(msg, "id") and msg.id):
            continue
        if hasattr(msg, "type") and msg.type == "tool":
            remove_messages.append(RemoveMessage(id=msg.id))
        elif hasattr(msg, "type") and msg.type == "ai" and getattr(msg, "tool_calls", None):
            remove_messages.append(RemoveMessage(id=msg.id))

    if remove_messages:
        print(f"  [merge_answers] 清除 {len(remove_messages)} 條 tool 相關訊息")

    history_items = ["merge_answers"]
    if topic_resolved:
        history_items.append("topic_resolved")

    return {
        "answer": answer,
        "messages": remove_messages,
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

        fact_attrs = ", ".join(USER_PROFILE_CONFIG.get("fact_attributes", []))
        prompt = load_prompt_template(
            PROMPTS_CONFIG.get("profile_updater", "agents/prompts/update_profile.md"),
            domain=domain,
            existing_profile=existing_profile if existing_profile else "(empty - new user)",
            question=question,
            answer=answer,
            fact_attributes=fact_attrs if fact_attrs else "phone, address, device_model, device_brand",
        )

        try:
            response = await llm.ainvoke(prompt)
            raw_text = response.content.strip()

            # Strip code fence if LLM wraps output in ```json ... ```
            cleaned = re.sub(r'^```(?:json)?\s*', '', raw_text)
            cleaned = re.sub(r'\s*```$', '', cleaned)

            try:
                parsed = json.loads(cleaned)

                # Write hard_facts to PostgreSQL via SCD Type 2
                hard_facts = parsed.get("hard_facts", {})
                if hard_facts and isinstance(hard_facts, dict):
                    for key, val in hard_facts.items():
                        if val is not None and str(val).strip():
                            await profile_manager.update_fact(user_id, key, str(val).strip())
                            print(f"  [update_profile] fact 寫入: {key}={val}")

                # Write soft_profile to .md file
                soft_profile = parsed.get("soft_profile")
                if soft_profile and isinstance(soft_profile, str) and len(soft_profile.strip()) >= 10:
                    await profile_manager.save_profile(user_id, soft_profile.strip())
                    print(f"  [update_profile] 已更新 {user_id} 的軟輪廓")

            except json.JSONDecodeError:
                # Fallback: treat entire response as soft profile (backward compatible)
                print("  [update_profile] JSON 解析失敗，fallback 為軟輪廓存檔")
                if raw_text and len(raw_text) >= 10:
                    await profile_manager.save_profile(user_id, raw_text)

        except Exception as e:
            print(f"  [update_profile] 更新輪廓失敗: {e}")

    return {
        "history": ["update_profile"]
    }


def _strip_markdown(text: str) -> str:
    """移除常見 Markdown 標記，保留換行與純文字。"""
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)   # # 標題
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)                 # **粗體**
    text = re.sub(r'__(.+?)__', r'\1', text)                     # __粗體__
    text = re.sub(r'\*(.+?)\*', r'\1', text)                     # *斜體*
    text = re.sub(r'_(.+?)_', r'\1', text)                       # _斜體_
    text = re.sub(r'~~(.+?)~~', r'\1', text)                     # ~~刪除線~~
    text = re.sub(r'`(.+?)`', r'\1', text)                       # `行內程式碼`
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)  # - 或 * 無序列表符號
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)         # [文字](連結)
    return text.strip()


async def post_process(state: GraphState):
    """回傳最終 answer + 建構 LINE Message 物件"""
    print("  [post_process] 回傳最終回覆...")
    answer = state.get("answer", "")
    answer = _strip_markdown(answer)
    ui_hints = state.get("ui_hints", [])
    response_ui = build_line_messages(answer, ui_hints)
    debug_log_final_answer("head → 使用者（最終回覆）", answer)
    return {
        "answer": answer,
        "response_ui": response_ui,
        "history": ["post_process"],
    }
