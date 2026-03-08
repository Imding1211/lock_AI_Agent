"""
訊息完整性評估模組 — 規則式 + LLM 判斷，用於智慧防抖。
"""

import json
import os
import re

# 句尾標點
_END_PUNCTUATION = set("？！。?!.~…")

# 疑問詞
_QUESTION_WORDS = ["怎麼", "如何", "什麼", "嗎", "呢", "為什麼", "哪", "幾", "多少", "能不能", "可以嗎", "是否"]

# 常見完整短句（精確匹配）
_COMPLETE_PHRASES = [
    "你好", "您好", "哈囉", "嗨", "hi", "hello",
    "好的", "好", "ok", "OK",
    "謝謝", "感謝", "感恩", "3Q", "thank",
    "轉接客服", "轉人工", "真人客服",
    "不用了", "沒事了", "沒問題",
    "對", "是", "不是", "不要", "不用",
    "掰掰", "bye", "再見",
]

# 動作動詞
_ACTION_VERBS = ["查", "幫", "設定", "安裝", "修", "換", "買", "退", "寄", "開", "關", "連", "綁", "解", "重設", "更新", "下載"]

# 句尾疑問模式（幾乎 100% 是完整問句）
_QUESTION_ENDINGS = ["怎麼辦", "怎麼樣", "好不好", "行不行", "可不可以", "對不對", "是不是"]


def evaluate_completeness(text: str) -> float:
    """
    規則式評分 0.0~1.0，判斷訊息是否為完整語句。

    六條規則疊加計分：
    1. 句尾標點      +0.4
    2. 文字長度      +0.1~0.3
    3. 疑問詞        +0.2
    4. 常見短句      +0.5
    5. 動詞          +0.1
    6. 句尾疑問模式  +0.3
    """
    if not text or not text.strip():
        return 0.0

    text = text.strip()
    score = 0.0

    # 規則 1：句尾標點
    if text[-1] in _END_PUNCTUATION:
        score += 0.4

    # 規則 2：文字長度
    length = len(text)
    if length >= 10:
        score += 0.3
    elif length >= 6:
        score += 0.2
    elif length >= 4:
        score += 0.1

    # 規則 3：疑問詞
    for word in _QUESTION_WORDS:
        if word in text:
            score += 0.2
            break

    # 規則 4：常見完整短句
    text_lower = text.lower()
    for phrase in _COMPLETE_PHRASES:
        if text_lower == phrase.lower():
            score += 0.5
            break

    # 規則 5：動作動詞
    for verb in _ACTION_VERBS:
        if verb in text:
            score += 0.1
            break

    # 規則 6：句尾疑問模式（「怎麼辦」「好不好」等幾乎就是完整問句）
    for ending in _QUESTION_ENDINGS:
        if text.endswith(ending):
            score += 0.3
            break

    return min(score, 1.0)


def calculate_debounce_wait(text: str, config: dict) -> float:
    """
    根據完整性分數計算等待時間（秒）。

    - score >= threshold → min_wait
    - score < threshold  → 線性插值到 max_wait
    """
    min_wait = config.get("min_wait", 1.5)
    max_wait = config.get("max_wait", 5.0)
    threshold = config.get("completeness_threshold", 0.5)

    score = evaluate_completeness(text)

    if score >= threshold:
        return min_wait

    # 線性插值：score 越低，等待越久
    if threshold > 0:
        ratio = score / threshold
    else:
        ratio = 0.0

    wait = max_wait - ratio * (max_wait - min_wait)
    return wait


def create_debounce_llm(debounce_config: dict, llm_config: dict):
    """根據 [debounce] 設定建立 LLM 實例，使用 [llm] 的語言模型設定。返回 None 如果未啟用。"""
    if not debounce_config.get("enabled", False):
        return None

    from llms import get_llm
    try:
        return get_llm(llm_config)
    except Exception as e:
        print(f"[Debounce] 建立 LLM 失敗: {e}，退回規則式。")
        return None


async def llm_evaluate(text: str, intents: list[dict], llm) -> dict:
    """
    呼叫 LLM 同時回傳完整性分數與預判意圖。

    回傳格式: {"completeness": 0.8, "intent": "troubleshooting"}
    失敗時 fallback 到規則式（intent 為 None）。
    """
    if not llm or not text or not text.strip():
        return {"completeness": evaluate_completeness(text), "intent": None}

    intent_descriptions = "\n".join([
        f"- {intent['name']}: {intent['description']}"
        for intent in intents
    ])
    intent_names = [intent["name"] for intent in intents]

    prompt = f"""You are a message analyzer for a smart lock customer service chatbot.
Analyze the user's message and return a JSON object with two fields:

1. "completeness": A float from 0.0 to 1.0 indicating how complete the message is.
   - 1.0 = fully formed question or statement
   - 0.0 = meaningless fragment
   - Consider: Does it express a complete thought? Can it be answered as-is?

2. "intent": The most likely intent category from the list below.

Intent categories:
{intent_descriptions}

User message: {text}

Output ONLY a valid JSON object, no other text.
Example: {{"completeness": 0.85, "intent": "troubleshooting"}}"""

    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        # 從回覆中提取 JSON
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if not match:
            raise ValueError("LLM 回覆中找不到 JSON")

        result = json.loads(match.group(0))

        # 驗證 completeness
        completeness = float(result.get("completeness", 0.5))
        completeness = max(0.0, min(1.0, completeness))

        # 驗證 intent
        intent = result.get("intent")
        if intent not in intent_names:
            intent = None

        return {"completeness": completeness, "intent": intent}

    except Exception as e:
        print(f"[Debounce] LLM 評估失敗 ({e})，退回規則式。")
        return {"completeness": evaluate_completeness(text), "intent": None}


def generate_clarification_text(intents: list[dict]) -> str:
    """
    根據 intents 設定生成反問文字，引導使用者補充資訊或選擇意圖方向。
    跳過 out_of_domain，使用 intent 的 label 欄位（無 label 則跳過）。
    """
    options = []
    for intent in intents:
        label = intent.get("label")
        if label:
            options.append(f"• {label}")

    text = "不好意思，能否請您再說得更完整一些呢？\n"
    if options:
        text += "或是告訴我您想詢問的方向：\n"
        text += "\n".join(options)
        text += "\n\n您也可以直接補充更完整的描述喔！"
    else:
        text += "請補充更完整的描述，讓我能更好地協助您！"

    return text
