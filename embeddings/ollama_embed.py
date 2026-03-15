import os
from langchain_ollama import OllamaEmbeddings

def build_ollama_embedding(config: dict):
    model_name = config.get("embedding_model", "nomic-embed-text")
    env_url_name = config.get("embedding_base_url_env", "OLLAMA_BASE_URL")
    base_url = os.getenv(env_url_name) or config.get("embedding_base_url", "http://localhost:11434")

    dimensions = config.get("embedding_dimensions")
    if dimensions:
        print(f"[!] Ollama Embedding 不支援自訂維度（embedding_dimensions={dimensions}），將使用模型預設維度")

    print(f"[*] 初始化 Embedding: 載入 Ollama (模型: {model_name})")

    return OllamaEmbeddings(
        model=model_name,
        base_url=base_url
    )
