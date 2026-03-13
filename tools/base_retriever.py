import asyncio
from abc import abstractmethod
from langchain_core.tools import StructuredTool
from .base import BaseTool


class BaseRetriever(BaseTool):
    @abstractmethod
    async def aretrieve(self, question: str) -> str:
        pass

    def setup(self):
        pass

    def as_langchain_tool(self) -> StructuredTool:
        name = self.config["name"]
        description = self.config.get("description", name)
        instance = self

        async def _aretrieve(query: str) -> str:
            """根據使用者問題檢索相關資料。參數 query: 使用者的問題或關鍵字"""
            print(f"  [Tool 呼叫] {name}: 正在檢索 '{query}'...")
            result = await instance.aretrieve(query)
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
