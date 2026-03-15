from .ollama_embed import build_ollama_embedding
from .vertexai_embed import build_vertexai_embedding

# 註冊表：將字串對應到對應的建造函數
REGISTRY = {
    "ollama": build_ollama_embedding,
    "vertexai": build_vertexai_embedding,
}

def get_embedding(config: dict = None):
    # 若 config 未帶 embedding_provider，fallback 至全域 EMBEDDING_CONFIG
    if not config or not config.get("embedding_provider"):
        from core.config import EMBEDDING_CONFIG
        cfg = {f"embedding_{k}": v for k, v in EMBEDDING_CONFIG.items()}
        cfg.setdefault("embedding_provider", "ollama")
    else:
        cfg = config

    provider = cfg.get("embedding_provider", "ollama")
    builder = REGISTRY.get(provider)

    if not builder:
        raise ValueError(f"未知的 Embedding 供應商: {provider}，請確認是否已在 embeddings/__init__.py 註冊")

    return builder(cfg)