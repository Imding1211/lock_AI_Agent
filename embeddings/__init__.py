from .ollama_embed import build_ollama_embedding
from .vertexai_embed import build_vertexai_embedding

# 註冊表：將字串對應到對應的建造函數
REGISTRY = {
    "ollama": build_ollama_embedding,
    "vertexai": build_vertexai_embedding,
}

def get_embedding(config: dict):
    provider = config.get("embedding_provider")
    if not provider:
        raise ValueError(
            f"[[databases]] 缺少 embedding_provider 欄位，"
            f"請在 config.toml 對應的資料庫區塊中設定"
        )

    builder = REGISTRY.get(provider)
    if not builder:
        raise ValueError(
            f"未知的 Embedding 供應商: {provider}，"
            f"請確認是否已在 embeddings/__init__.py 註冊"
        )

    return builder(config)
