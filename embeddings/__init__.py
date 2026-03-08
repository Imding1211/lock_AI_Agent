from .ollama_embed import build_ollama_embedding

# 註冊表：將字串對應到對應的建造函數
REGISTRY = {
    "ollama": build_ollama_embedding,
    # "openai": build_openai_embedding,  # 未來擴充時把這行註解打開即可
}

def get_embedding(config: dict):
    provider = config.get("embedding_provider", "ollama")
    builder = REGISTRY.get(provider)
    
    if not builder:
        raise ValueError(f"未知的 Embedding 供應商: {provider}，請確認是否已在 embeddings/__init__.py 註冊")
    
    return builder(config)