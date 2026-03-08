import json
import re
from typing import Literal
from langchain_core.runnables import RunnableConfig
from core.config import DB_CONFIG, LLM_CONFIG, INTENTS_CONFIG, REQUIRED_SLOTS, SYSTEM_CONFIG, USER_PROFILE_CONFIG, MEMORY_CONFIG
from profiles import ProfileManager
from graph.state import GraphState
from retrievers import get_retriever
from llms import get_llm

llm = get_llm(LLM_CONFIG)
profile_manager = ProfileManager(USER_PROFILE_CONFIG)

async def safe_llm_invoke(prompt: str, fallback: str = "") -> str:
    """Wrap llm.ainvoke() with error handling."""
    try:
        response = await llm.ainvoke(prompt)
        return response.content.strip()
    except Exception as e:
        print(f"  [LLM 錯誤] llm.ainvoke 呼叫失敗: {e}")
        return fallback

def parse_llm_json(text: str) -> dict:
    """工具函數：從 LLM 的回覆中安全地提取 JSON"""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}

async def load_user_profile(state: GraphState, config: RunnableConfig):
    print("  [使用者輪廓] 正在載入使用者背景資訊...")
    if not USER_PROFILE_CONFIG.get("enabled", False):
        print("  [使用者輪廓] 功能未啟用，跳過。")
        return {"user_profile": "", "slots": {}, "history": ["load_user_profile"]}

    cfg = config.get("configurable", {})
    user_id = cfg.get("user_id") or cfg.get("thread_id", "anonymous")
    content = await profile_manager.load_profile(user_id)

    if content:
        print(f"  [使用者輪廓] 已載入 {user_id} 的輪廓 ({len(content)} 字元)")
    else:
        print(f"  [使用者輪廓] {user_id} 尚無歷史輪廓")

    prefilled = {}
    if content and REQUIRED_SLOTS:
        slots_description = "\n".join([f"- {k}: {v}" for k, v in REQUIRED_SLOTS.items()])
        prompt = f"""
        Extract the following information from the user profile.
        Output ONLY a valid JSON object.
        If a value is found, output the string. If not found, output null.

        Required Information:
        {slots_description}

        [User Profile]
        {content}
        """
        raw = await safe_llm_invoke(prompt, fallback="{}")
        extracted = parse_llm_json(raw)
        prefilled = {k: v for k, v in extracted.items() if v and v != "null" and k in REQUIRED_SLOTS}
        if prefilled:
            print(f"  [使用者輪廓] 從輪廓預填 slots: {prefilled}")

    return {"user_profile": content, "slots": prefilled, "history": ["load_user_profile"]}


async def update_user_profile(state: GraphState, config: RunnableConfig):
    print("  [使用者輪廓] 正在更新使用者背景資訊...")
    if not USER_PROFILE_CONFIG.get("enabled", False):
        print("  [使用者輪廓] 功能未啟用，跳過。")
        return {"history": ["update_user_profile"]}

    answer = state.get("answer", "")
    if not answer:
        print("  [使用者輪廓] 無回覆內容，跳過更新。")
        return {"history": ["update_user_profile"]}

    cfg = config.get("configurable", {})
    user_id = cfg.get("user_id") or cfg.get("thread_id", "anonymous")
    existing_profile = state.get("user_profile", "")
    question = state.get("question", "")

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
    3. If the user CORRECTS or UPDATES previously recorded information (e.g., "我換了新鎖", "電話改成...", "地址不對，應該是..."), REPLACE the old value with the new one. The user's latest statement always takes priority over existing profile data.
    4. Merge new information into the existing profile.
    5. Output the COMPLETE updated profile in Markdown format (Traditional Chinese).
    6. If there is NO new personal information to record, output the existing profile as-is.
    7. Do NOT include the conversation content itself, only extracted personal facts.
    8. Keep it concise and well-organized with headers.

    Output the updated profile in Markdown:
    """

    updated = await safe_llm_invoke(prompt, fallback="")

    if not updated or len(updated) < 10:
        print(f"  [使用者輪廓] LLM 回傳內容過短（{len(updated)} 字元），保留原有輪廓。")
        return {"history": ["update_user_profile"]}

    await profile_manager.save_profile(user_id, updated)
    print(f"  [使用者輪廓] 已更新 {user_id} 的輪廓")

    return {"user_profile": updated, "history": ["update_user_profile"]}


async def extract_slots(state: GraphState):
    print("  [資訊盤點] 正在檢查是否有遺漏的必填資訊...")
    
    if not REQUIRED_SLOTS:
        return {"history": ["extract_slots"]}
        
    current_slots = state.get("slots", {})
    if current_slots is None:
        current_slots = {}

    slots_description = "\n".join([f"- {k}: {v}" for k, v in REQUIRED_SLOTS.items()])
    
    prompt = f"""
    You are an information extraction assistant.
    Extract the following required information from the Latest Query.
    
    Required Information to extract:
    {slots_description}
    
    Latest Query: {state.get('standalone_query', state['question'])}
    
    Output ONLY a valid JSON object. Keys must be the required information names.
    - If a value is found in the query, output the string.
    - If the user explicitly states they do not know or cannot provide the information, output "UNKNOWN".
    - If the information is simply not mentioned yet, output null.
    
    Example: {{"device_model": "UNKNOWN", "device_brand": null}}
    """
    
    raw = await safe_llm_invoke(prompt, fallback="{}")
    extracted = parse_llm_json(raw)

    updated_slots = {**current_slots}
    for key, value in extracted.items():
        if value is not None and value != "null":
            current_value = current_slots.get(key)
            if value == "UNKNOWN" and current_value and current_value != "UNKNOWN":
                print(f"  [盤點結果] 欄位 {key} 保留既有值 '{current_value}'（忽略 UNKNOWN）")
                continue
            updated_slots[key] = value
            print(f"  [盤點結果] 欄位 {key} 更新為 -> '{value}'")
            
    return {"slots": updated_slots, "history": ["extract_slots"]}

async def ask_missing_slots(state: GraphState):
    print("  [LLM 生成中] 發現遺漏資訊，正在生成反問句...")
    current_slots = state.get("slots", {})
    
    # 找出還缺少的欄位
    missing_keys = [k for k in REQUIRED_SLOTS.keys() if not current_slots.get(k)]
    missing_descriptions = [REQUIRED_SLOTS[k] for k in missing_keys]
    
    prompt = f"""
    你是一位親切的客服人員。使用者問了一個問題，但我們需要更多資訊才能協助他。
    請根據以下缺少的資訊，產生一句「親切的反問句」來詢問使用者。
    
    缺少的資訊：
    {', '.join(missing_descriptions)}
    
    使用者的原問題：{state['question']}
    
    要求：
    1. 語氣委婉、禮貌。
    2. 不要回答原問題，只要負責把缺少的資訊問出來就好。
    """
    
    answer = await safe_llm_invoke(prompt, fallback="不好意思，系統處理遇到一些問題，能否再告訴我一次您的設備品牌和型號呢？")

    new_exchange = [
        f"User: {state['question']}",
        f"AI: {answer}"
    ]

    return {
        "answer": answer,
        "history": ["ask_missing_slots"],
        "chat_history": new_exchange
    }

async def rewrite_query(state: GraphState):
    print("  [問題改寫] 正在根據歷史紀錄重構完整問題...")
    past_dialogue = "\n".join(state.get("chat_history", []))
    user_profile = state.get("user_profile", "")
    original_question = state["question"]
    topic_shift_enabled = MEMORY_CONFIG.get("topic_shift_detection", False)

    if not past_dialogue and not user_profile:
        print(f"  [改寫結果] 無歷史紀錄，使用原問題: '{original_question}'")
        return {"standalone_query": original_question, "history": ["rewrite_query"]}

    profile_section = ""
    if user_profile:
        profile_section = f"""
    [User Profile — background info about this user]
    {user_profile}
    """

    # 有對話歷史且啟用話題轉換偵測 → 同時做話題比對 + 改寫
    if past_dialogue and topic_shift_enabled:
        shift_prompt = f"""
    You are a query rewriter for a customer service system.
    Given the conversation history and the user's latest question, do TWO things:
    1. Determine: Is the latest question about the SAME topic as the conversation history?
    2. Rewrite the query accordingly.
    {profile_section}
    [Conversation History]
    {past_dialogue}

    [Latest Question]
    {original_question}

    Instructions:
    - If the latest question is about the SAME topic: rewrite it as a standalone query incorporating relevant history context.
    - If the latest question is about a DIFFERENT topic: summarize the previous topic in a brief phrase, and rewrite the new question as a completely standalone query WITHOUT using any conversation history context.
    - If the user profile contains relevant device info (brand, model) and the question lacks it, incorporate it into the rewritten query.

    Output ONLY a valid JSON object with these fields:
    - "same_topic": boolean
    - "previous_topic_summary": string (brief summary of previous topic if different, null if same)
    - "rewritten_query": string (the rewritten standalone question)

    Example (same topic): {{"same_topic": true, "previous_topic_summary": null, "rewritten_query": "..."}}
    Example (different topic): {{"same_topic": false, "previous_topic_summary": "指紋辨識失靈的問題", "rewritten_query": "..."}}
    """

        raw = await safe_llm_invoke(shift_prompt, fallback="{}")
        result = parse_llm_json(raw)

        same_topic = result.get("same_topic", True)
        previous_topic_summary = result.get("previous_topic_summary") or ""
        rewritten_query = result.get("rewritten_query", original_question)

        if not same_topic and previous_topic_summary:
            print(f"  [話題偵測] 偵測到話題轉換：「{previous_topic_summary}」→ 新問題")
            print(f"  [改寫結果] 獨立問題 -> '{rewritten_query}'")
            return {
                "standalone_query": rewritten_query,
                "previous_topic": previous_topic_summary,
                "history": ["rewrite_query", "topic_shifted"]
            }
        else:
            print(f"  [話題偵測] 同一話題，正常改寫")
            print(f"  [改寫結果] 獨立問題 -> '{rewritten_query}'")
            return {"standalone_query": rewritten_query, "history": ["rewrite_query"]}

    # 無對話歷史或未啟用話題偵測 → 原有改寫邏輯
    prompt = f"""
    Given the following context and the user's latest question,
    rewrite the user's question to be a standalone query that contains all the necessary context.
    Do not answer the question, just rewrite it.
    If the latest question is already standalone and no useful context can be added, just output the original question.
    If the user profile contains relevant device info (brand, model) and the question lacks it, incorporate it into the rewritten query.
    {profile_section}
    [Conversation History]
    {past_dialogue if past_dialogue else "(none)"}

    [Latest Question]
    {original_question}

    Standalone Question:
    """

    rewritten_query = await safe_llm_invoke(prompt, fallback=original_question)
    print(f"  [改寫結果] 獨立問題 -> '{rewritten_query}'")

    return {"standalone_query": rewritten_query, "history": ["rewrite_query"]}

def create_retrieve_node(db_config: dict):
    node_name = db_config["name"]
    db_type = db_config.get("type", "unknown")
    retriever_instance = get_retriever(db_config)

    async def retrieve(state: GraphState):
        search_query = state.get("standalone_query", state["question"])
        print(f"  [檢索中] 正在拿 '{search_query}' 查詢 {node_name} (類型: {db_type})...")
        context = await retriever_instance.aretrieve(search_query)
        return {"context": context, "history": [node_name]}
    
    return retrieve

async def detect_intent(state: GraphState):
    # 如果防抖階段已預判 intent，直接沿用
    if state.get("intent"):
        print(f"  [意圖偵測] 使用預判意圖 -> '{state['intent']}'")
        return {"history": ["detect_intent(pre-detected)"]}

    print("  [意圖偵測] 正在分析使用者問題的分類...")
    search_query = state.get("standalone_query", state["question"])
    
    intent_descriptions = "\n".join([
        f"- {intent['name']}: {intent['description']}" 
        for intent in INTENTS_CONFIG
    ])
    intent_names = [intent['name'] for intent in INTENTS_CONFIG]
    
    prompt = f"""
    You are an intent classification assistant.
    Analyze the user's query and classify it into EXACTLY ONE of the following categories:
    
    Categories:
    {intent_descriptions}
    
    User Query: {search_query}
    
    Instructions:
    Output EXACTLY the category name from the list above. Do not output anything else.
    If it does not match any specific category, output "{intent_names[-1]}".
    """
    
    detected_intent = await safe_llm_invoke(prompt, fallback=intent_names[-1])

    if detected_intent not in intent_names:
        detected_intent = intent_names[-1]
        
    print(f"  [分析結果] 判定意圖為 -> '{detected_intent}'")
    return {"intent": detected_intent, "history": ["detect_intent"]}

async def generate_answer(state: GraphState):
    print("  [LLM 生成中] 正在根據檢索到的資料整理最終回覆...")
    user_profile = state.get("user_profile", "")

    # 話題轉換時，不使用舊的 chat_history（避免舊話題污染新回答）
    past_dialogue = ""
    if not state.get("previous_topic"):
        past_dialogue = "\n".join(state.get("chat_history", []))

    profile_section = ""
    if user_profile:
        profile_section = f"""
    【使用者背景資訊】:
    {user_profile}
"""

    prompt = f"""
    你是一位專業、友善的客服人員。
    請參考【歷史對話紀錄】，並「嚴格根據」以下提供的【參考資料】來回答【使用者最新問題】。

    要求：
    1. 語氣要親切自然，就像真人在對話一樣。
    2. 不要加入參考資料以外的虛構資訊。
    3. 如果參考資料內容有點雜亂，請幫忙條理化。
    4. 若有【使用者背景資訊】，請善用這些資訊提供更個人化的回覆。

    【歷史對話紀錄】:
    {past_dialogue}
{profile_section}
    【參考資料】:
    {state['context']}

    【使用者最新問題】:
    {state['question']}
    """

    answer = await safe_llm_invoke(prompt, fallback="不好意思，系統暫時無法產生回覆，請稍後再試一次。")

    current_slots = state.get("slots", {})
    has_unknown = any(val == "UNKNOWN" for val in current_slots.values())

    if has_unknown:
        answer += "\n\n(溫馨提示：由於目前缺少您設備的品牌或型號，以上提供的是通用的排除方法。如果還是無法解決您的問題，請問需要為您轉接真人客服專員嗎？)"

    # 話題轉換時，附上關心前一話題的語句，並標記 topic_resolved 以遞增 session
    history_items = ["generate"]
    if state.get("previous_topic"):
        answer += f"\n\n另外，想關心一下您之前「{state['previous_topic']}」的問題有順利解決嗎？如果還需要協助，隨時跟我說喔！"
        history_items.append("topic_resolved")
        print(f"  [話題偵測] 附上關心語句，標記 topic_resolved")

    new_exchange = [
        f"User: {state['question']}",
        f"AI: {answer}"
    ]

    return {
        "answer": answer,
        "history": history_items,
        "chat_history": new_exchange
    }

async def out_of_domain(state: GraphState):
    domain = SYSTEM_CONFIG.get('domain', '電子鎖')
    return {"answer": f"不好意思，我是{domain}的專屬客服，這個問題可能超出我的服務範圍了。\n如果您有任何關於{domain}的問題，歡迎隨時詢問我喔！", "history": ["out_of_domain"]}

async def transfer_to_human(state: GraphState):
    user_profile = state.get("user_profile", "")
    slots = state.get("slots", {})

    # 從 slots 取得品牌型號
    brand = slots.get("device_brand", "")
    model = slots.get("device_model", "")
    brand_model = f"{brand} {model}".strip() if (brand or model) else ""

    # 從 user_profile 用 regex 提取電話與地址
    phone = ""
    address = ""
    if user_profile:
        phone_match = re.search(r'09\d{2}[\-\s]?\d{3}[\-\s]?\d{3}', user_profile)
        if phone_match:
            phone = phone_match.group()
        addr_match = re.search(r'[\u4e00-\u9fff]*(?:市|縣)[\u4e00-\u9fff]*(?:區|鄉|鎮|市)[\u4e00-\u9fff\d\s\-]*(?:路|街|巷|弄|號|樓)[\u4e00-\u9fff\d\s\-]*', user_profile)
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

    return {"answer": answer, "history": ["human", "topic_resolved"]}

async def decide_sufficiency(state: GraphState) -> Literal["sufficient", "insufficient"]:
    search_query = state.get("standalone_query", state["question"])
    print(f"  [LLM 思考中...] 判斷資料是否足以回答 '{search_query}'，且是否符合業務範圍")
    
    prompt = f"""
    You are a strict evaluator. Your task is to verify if the Context is suitable to answer the Question.

    [Business Domain]: {SYSTEM_CONFIG.get('domain', '電子鎖')}
    [Question]: {search_query}
    [Context]: {state['context']}

    You must evaluate based on these TWO conditions:
    1. DOMAIN: The core subject of BOTH the Question and the Context MUST be strictly about the [Business Domain].
    2. SUFFICIENCY: The Context MUST explicitly contain the answer to the Question.

    Instructions:
    - If the subject matter is outside the [Business Domain], you MUST output "NO".
    - If the Context does not contain the answer, you MUST output "NO".
    - If and ONLY if BOTH conditions are fully met, output "YES".

    Output EXACTLY "YES" or "NO". Do not output any explanations.
    """
    
    raw = await safe_llm_invoke(prompt, fallback="NO")
    content = raw.upper()
    
    print(f"  [Grader 判斷結果] 模型回傳 -> '{content}'")
    if "查無相關文件" in state["context"]:
        print("  [警告] 檢索結果為空，請確認資料庫內是否有資料！")

    if "YES" in content:
        return "sufficient"
    return "insufficient"