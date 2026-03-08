import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.debounce import evaluate_completeness, calculate_debounce_wait, llm_evaluate, create_debounce_llm, generate_clarification_text


# ============================================================
# evaluate_completeness 測試
# ============================================================

class TestEvaluateCompleteness:
    """測試訊息完整性評分"""

    def test_complete_question_with_punctuation(self):
        """完整問句：句尾標點 + 長度 + 疑問詞"""
        score = evaluate_completeness("指紋辨識失靈怎麼辦？")
        assert score >= 0.8

    def test_greeting_hello(self):
        """問候語應為完整短句"""
        score = evaluate_completeness("你好")
        assert score >= 0.5

    def test_greeting_ok(self):
        """確認語應為完整短句"""
        score = evaluate_completeness("好")
        assert score >= 0.5

    def test_greeting_thanks(self):
        """感謝語應為完整短句"""
        score = evaluate_completeness("謝謝")
        assert score >= 0.5

    def test_fragment_short(self):
        """片段文字：無標點、短、無特徵"""
        score = evaluate_completeness("門鎖")
        assert score < 0.5

    def test_fragment_my(self):
        """片段：「我的」"""
        score = evaluate_completeness("我的")
        assert score < 0.5

    def test_short_command(self):
        """短指令帶動詞（5字，長度+0.1、動詞+0.1）"""
        score = evaluate_completeness("幫我查訂單")
        assert score >= 0.2

    def test_transfer_human(self):
        """轉接客服是完整短句"""
        score = evaluate_completeness("轉接客服")
        assert score >= 0.5

    def test_long_sentence_no_punctuation(self):
        """較長句子即使沒標點也有一定分數"""
        score = evaluate_completeness("我想要安裝新的電子鎖在前門")
        assert score >= 0.3

    def test_question_word_how(self):
        """含疑問詞"""
        score = evaluate_completeness("如何設定密碼")
        assert score >= 0.4

    def test_empty_string(self):
        """空字串應為 0"""
        assert evaluate_completeness("") == 0.0

    def test_whitespace_only(self):
        """純空白應為 0"""
        assert evaluate_completeness("   ") == 0.0

    def test_emoji_only(self):
        """純 emoji 很短，分數低"""
        score = evaluate_completeness("👍")
        assert score < 0.5

    def test_english_hi(self):
        """英文問候"""
        score = evaluate_completeness("hello")
        assert score >= 0.5

    def test_mixed_chinese_english(self):
        """中英混合長句"""
        score = evaluate_completeness("我的lock密碼忘記了怎麼辦？")
        assert score >= 0.7

    def test_score_capped_at_one(self):
        """分數不超過 1.0"""
        # 長句 + 標點 + 疑問詞 + 動詞 → 可能超過 1.0，應被 cap
        score = evaluate_completeness("請問如何幫我重設電子鎖的密碼呢？")
        assert score <= 1.0

    def test_bye(self):
        """告別語"""
        score = evaluate_completeness("掰掰")
        assert score >= 0.5


# ============================================================
# calculate_debounce_wait 測試
# ============================================================

class TestCalculateDebounceWait:
    """測試等待時間計算"""

    DEFAULT_CONFIG = {
        "min_wait": 1.5,
        "max_wait": 5.0,
        "completeness_threshold": 0.5,
    }

    def test_complete_message_gets_min_wait(self):
        """完整訊息 → 最短等待"""
        wait = calculate_debounce_wait("指紋辨識失靈怎麼辦？", self.DEFAULT_CONFIG)
        assert wait == 1.5

    def test_fragment_gets_max_wait(self):
        """片段訊息 → 最長等待"""
        wait = calculate_debounce_wait("門鎖", self.DEFAULT_CONFIG)
        assert wait == 5.0

    def test_greeting_gets_min_wait(self):
        """問候語 → 最短等待"""
        wait = calculate_debounce_wait("你好", self.DEFAULT_CONFIG)
        assert wait == 1.5

    def test_empty_gets_max_wait(self):
        """空字串 → 最長等待"""
        wait = calculate_debounce_wait("", self.DEFAULT_CONFIG)
        assert wait == 5.0

    def test_wait_between_min_and_max(self):
        """中間分數 → 介於 min 和 max 之間"""
        wait = calculate_debounce_wait("設定", self.DEFAULT_CONFIG)
        assert 1.5 <= wait <= 5.0

    def test_custom_config(self):
        """自訂設定"""
        config = {
            "min_wait": 1.0,
            "max_wait": 3.0,
            "completeness_threshold": 0.5,
        }
        wait = calculate_debounce_wait("你好", config)
        assert wait == 1.0

    def test_missing_config_uses_defaults(self):
        """缺少設定 key 時用預設值"""
        wait = calculate_debounce_wait("你好", {})
        assert wait == 1.5


# ============================================================
# llm_evaluate 測試
# ============================================================

SAMPLE_INTENTS = [
    {"name": "troubleshooting", "description": "設備故障"},
    {"name": "order_status", "description": "查詢訂單"},
    {"name": "general_knowledge", "description": "一般問題"},
]


class TestLlmEvaluate:
    """測試 LLM 完整性 + 意圖預判"""

    @pytest.mark.asyncio
    async def test_normal_response(self):
        """LLM 正常回傳 JSON"""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"completeness": 0.9, "intent": "troubleshooting"}'
        )

        result = await llm_evaluate("指紋辨識失靈怎麼辦？", SAMPLE_INTENTS, mock_llm)
        assert result["completeness"] == 0.9
        assert result["intent"] == "troubleshooting"

    @pytest.mark.asyncio
    async def test_llm_returns_json_with_extra_text(self):
        """LLM 回傳帶有多餘文字的 JSON"""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='Here is the result: {"completeness": 0.7, "intent": "order_status"} done.'
        )

        result = await llm_evaluate("查一下我的訂單", SAMPLE_INTENTS, mock_llm)
        assert result["completeness"] == 0.7
        assert result["intent"] == "order_status"

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self):
        """LLM 呼叫失敗 → fallback 到規則式"""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("API timeout")

        result = await llm_evaluate("你好", SAMPLE_INTENTS, mock_llm)
        # fallback 到規則式，intent 為 None
        assert result["completeness"] == evaluate_completeness("你好")
        assert result["intent"] is None

    @pytest.mark.asyncio
    async def test_json_parse_error_fallback(self):
        """LLM 回傳非 JSON → fallback 到規則式"""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content="I cannot process this request."
        )

        result = await llm_evaluate("門鎖", SAMPLE_INTENTS, mock_llm)
        assert result["completeness"] == evaluate_completeness("門鎖")
        assert result["intent"] is None

    @pytest.mark.asyncio
    async def test_invalid_intent_set_to_none(self):
        """LLM 回傳不在合法列表的 intent → intent 設為 None"""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"completeness": 0.6, "intent": "unknown_category"}'
        )

        result = await llm_evaluate("這是什麼", SAMPLE_INTENTS, mock_llm)
        assert result["completeness"] == 0.6
        assert result["intent"] is None

    @pytest.mark.asyncio
    async def test_completeness_clamped(self):
        """completeness 超出範圍會被 clamp 到 0.0~1.0"""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"completeness": 1.5, "intent": "troubleshooting"}'
        )

        result = await llm_evaluate("測試", SAMPLE_INTENTS, mock_llm)
        assert result["completeness"] == 1.0

    @pytest.mark.asyncio
    async def test_no_llm_fallback(self):
        """llm 為 None → 直接用規則式"""
        result = await llm_evaluate("你好", SAMPLE_INTENTS, None)
        assert result["completeness"] == evaluate_completeness("你好")
        assert result["intent"] is None

    @pytest.mark.asyncio
    async def test_empty_text(self):
        """空字串 → 直接用規則式"""
        mock_llm = AsyncMock()
        result = await llm_evaluate("", SAMPLE_INTENTS, mock_llm)
        assert result["completeness"] == 0.0
        assert result["intent"] is None
        mock_llm.ainvoke.assert_not_called()


# ============================================================
# create_debounce_llm 測試
# ============================================================

class TestCreateDebounceLlm:
    """測試防抖 LLM 建立"""

    def test_disabled_returns_none(self):
        """enabled=False → 回傳 None"""
        result = create_debounce_llm({"enabled": False}, {"provider": "gemini"})
        assert result is None

    def test_empty_config_returns_none(self):
        """空設定 → 回傳 None"""
        result = create_debounce_llm({}, {})
        assert result is None

    def test_unknown_provider_returns_none(self):
        """未知 provider → 回傳 None"""
        result = create_debounce_llm({"enabled": True}, {"provider": "nonexistent"})
        assert result is None


# ============================================================
# generate_clarification_text 測試
# ============================================================

class TestGenerateClarificationText:
    """測試反問文字生成"""

    def test_includes_labels(self):
        """有 label 的 intent 會出現在反問文字中"""
        intents = [
            {"name": "order_status", "label": "查詢訂單", "description": "..."},
            {"name": "troubleshooting", "label": "設備故障排除", "description": "..."},
        ]
        text = generate_clarification_text(intents)
        assert "查詢訂單" in text
        assert "設備故障排除" in text

    def test_skips_intents_without_label(self):
        """沒有 label 的 intent 不會出現"""
        intents = [
            {"name": "order_status", "label": "查詢訂單", "description": "..."},
            {"name": "out_of_domain", "description": "與電子鎖無關"},
        ]
        text = generate_clarification_text(intents)
        assert "查詢訂單" in text
        assert "out_of_domain" not in text
        assert "與電子鎖無關" not in text

    def test_empty_intents(self):
        """空 intents → 仍回傳反問文字"""
        text = generate_clarification_text([])
        assert "更完整" in text

    def test_all_intents_without_label(self):
        """全部 intent 都沒 label → 不列選項，仍回傳反問"""
        intents = [
            {"name": "out_of_domain", "description": "..."},
        ]
        text = generate_clarification_text(intents)
        assert "更完整" in text
        assert "•" not in text
