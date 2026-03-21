import asyncio
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from .base_retriever import BaseRetriever

class WebSearchRetriever(BaseRetriever):
    def setup(self):
        self.engine = self.config.get("search_engine", "duckduckgo")
        self.max_results = self.config.get("max_results", 3)

        print(f"[*] 初始化 Web Search 模組: 使用 {self.engine}...")

        if self.engine == "duckduckgo":
            wrapper = DuckDuckGoSearchAPIWrapper(max_results=self.max_results)
            self.search_tool = DuckDuckGoSearchResults(api_wrapper=wrapper)
        else:
            raise ValueError(f"尚未支援此搜尋引擎: {self.engine}")

    async def aretrieve(self, question: str) -> str:
        try:
            results = await asyncio.to_thread(self.search_tool.run, question)

            if not results or results.strip() == "":
                return "查無相關資訊。"
            return f"{results}"
        except Exception as e:
            return f"網頁搜尋發生錯誤: {e}"
