import asyncio
from langchain_core.tools import StructuredTool
from core.config import USER_PROFILE_CONFIG, PROMPTS_CONFIG
from core.constants import PHONE_REGEX, ADDRESS_REGEX
from profiles import ProfileManager
from agents import load_prompt_template
from .base import BaseTool


class TransferHumanTool(BaseTool):
    def setup(self):
        self.profile_manager = ProfileManager(USER_PROFILE_CONFIG)
        self.transfer_form_path = PROMPTS_CONFIG.get(
            "transfer_form", "agents/prompts/transfer_human_form.md"
        )

    async def generate_form(self, user_id: str = "anonymous", extra_text: str = "") -> str:
        """核心邏輯：載入 profile、regex 提取電話/地址、渲染 template。

        Args:
            user_id: 使用者 ID
            extra_text: 額外文字（例如 state["question"]），一起做 regex 提取
        """
        print(f"  [Tool 呼叫] transfer_to_human: user_id={user_id}")

        user_profile = await self.profile_manager.load_profile(user_id)

        combined_text = f"{user_profile}\n{extra_text}" if extra_text else (user_profile or "")

        phone = ""
        address = ""
        brand_model = ""
        if combined_text:
            phone_match = PHONE_REGEX.search(combined_text)
            if phone_match:
                phone = phone_match.group()
            addr_match = ADDRESS_REGEX.search(combined_text)
            if addr_match:
                address = addr_match.group().strip()

        has_info = any([brand_model, phone, address])
        header = "您好\n麻煩您確認並補充以下資訊" if has_info else "您好\n麻煩您留下以下資訊"

        answer = load_prompt_template(
            self.transfer_form_path,
            header=header, address=address, phone=phone, brand_model=brand_model,
        )
        return answer

    def as_langchain_tool(self) -> StructuredTool:
        instance = self

        async def _transfer(user_id: str = "anonymous") -> str:
            """當使用者明確堅持要求轉接真人客服，或涉及安全風險時，呼叫此工具。參數 user_id: 使用者 ID"""
            return await instance.generate_form(user_id)

        def _transfer_sync(user_id: str = "anonymous") -> str:
            return asyncio.run(_transfer(user_id))

        return StructuredTool.from_function(
            func=_transfer_sync,
            coroutine=_transfer,
            name="transfer_to_human",
            description="轉接真人客服。僅在以下情況使用：(1) 使用者明確堅持要求轉接真人客服 (2) 涉及安全風險（門鎖無法上鎖、疑似被破壞）。不要因為資料不足就轉接，應先嘗試提供通用建議。",
        )
