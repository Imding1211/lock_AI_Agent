from langchain_core.tools import StructuredTool
from core.config import DB_CONFIG
from .chroma_store import ChromaRetriever
from .pgvector_store import PGVectorRetriever
from .api_store import APIStoreRetriever
from .web_search import WebSearchRetriever
from .transfer_human import TransferHumanTool

REGISTRY = {
    "chroma": ChromaRetriever,
    "pgvector": PGVectorRetriever,
    "api": APIStoreRetriever,
    "web_search": WebSearchRetriever,
}


def get_retriever(db_config: dict):
    db_type = db_config.get("type")
    cls = REGISTRY.get(db_type)
    if not cls:
        raise ValueError(f"未知的資料庫類型: {db_type}")
    return cls(db_config)


def build_tools() -> dict[str, StructuredTool]:
    """根據 config.toml 建立所有工具，回傳 dict 方便 agent 按名稱取用"""
    tools = {}

    for db_config in DB_CONFIG:
        instance = get_retriever(db_config)
        tool = instance.as_langchain_tool()
        tools[tool.name] = tool
        print(f"[*] 已註冊工具: {tool.name} — {db_config.get('description', '')}")

    transfer = TransferHumanTool({})
    tools["transfer_to_human"] = transfer.as_langchain_tool()
    print(f"[*] 已註冊工具: transfer_to_human — 轉接真人客服")

    return tools
