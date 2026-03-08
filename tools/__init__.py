import asyncio
import re
from langchain_core.tools import StructuredTool
from core.config import DB_CONFIG, INTENTS_CONFIG, SYSTEM_CONFIG, REQUIRED_SLOTS, USER_PROFILE_CONFIG
from retrievers import get_retriever
from profiles import ProfileManager

profile_manager = ProfileManager(USER_PROFILE_CONFIG)


def _build_retriever_tool(db_config: dict) -> StructuredTool:
    """將單一 retriever 包裝為 LangChain StructuredTool"""
    name = db_config["name"]
    description = db_config.get("description", name)
    retriever_instance = get_retriever(db_config)

    async def _aretrieve(query: str) -> str:
        """根據使用者問題檢索相關資料。參數 query: 使用者的問題或關鍵字"""
        print(f"  [Tool 呼叫] {name}: 正在檢索 '{query}'...")
        result = await retriever_instance.aretrieve(query)
        print(f"  [Tool 結果] {name}: 回傳 {len(result)} 字元")
        return result

    def _retrieve_sync(query: str) -> str:
        return asyncio.run(_aretrieve(query))

    return StructuredTool.from_function(
        func=_retrieve_sync,
        coroutine=_aretrieve,
        name=name,
        description=f"搜尋「{description}」資料庫。當使用者的問題與「{description}」相關時使用此工具。",
    )


def _build_transfer_to_human_tool() -> StructuredTool:
    """建立轉接真人客服的工具"""

    async def _transfer(user_id: str = "anonymous") -> str:
        """當所有工具都無法回答使用者問題，或使用者明確要求轉接真人客服時，呼叫此工具。參數 user_id: 使用者 ID"""
        print(f"  [Tool 呼叫] transfer_to_human: user_id={user_id}")

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
        return answer

    def _transfer_sync(user_id: str = "anonymous") -> str:
        return asyncio.run(_transfer(user_id))

    return StructuredTool.from_function(
        func=_transfer_sync,
        coroutine=_transfer,
        name="transfer_to_human",
        description="轉接真人客服。當所有資料來源都無法回答使用者問題，或使用者明確要求轉接真人客服時使用。",
    )


def build_tools() -> list:
    """根據 config.toml 建立所有工具"""
    tools = []

    for db_config in DB_CONFIG:
        tool = _build_retriever_tool(db_config)
        tools.append(tool)
        print(f"[*] 已註冊工具: {tool.name} — {db_config.get('description', '')}")

    tools.append(_build_transfer_to_human_tool())
    print(f"[*] 已註冊工具: transfer_to_human — 轉接真人客服")

    return tools
