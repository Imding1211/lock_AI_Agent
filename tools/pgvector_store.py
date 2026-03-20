import asyncio
import json
import os
from functools import partial
from langchain_postgres import PGVector
from .base_retriever import BaseRetriever

from embeddings import get_embedding

UI_METADATA_DELIMITER = "\n===UI_METADATA===\n"


class PGVectorRetriever(BaseRetriever):
    def setup(self):
        self.collection_name = self.config.get("collection_name", self.config["name"])
        self.top_k = self.config.get("top_k", 2)

        connection_uri_env = self.config.get("connection_uri_env", "PG_VECTOR_URI")
        connection_uri = os.environ.get(connection_uri_env)
        if not connection_uri:
            raise ValueError(
                f"環境變數 {connection_uri_env} 未設定，"
                f"請在 .env 中設定 PostgreSQL 連線字串"
            )

        embed_fn = get_embedding(self.config)

        print(f"[*] 初始化 PGVector: collection={self.collection_name}...")

        self.vector_store = PGVector(
            embeddings=embed_fn,
            collection_name=self.collection_name,
            connection=connection_uri,
        )

        # 維度校驗
        expected_dim = self.config.get("embedding_dimensions")
        if expected_dim:
            test_vector = embed_fn.embed_query("test")
            actual_dim = len(test_vector)
            if actual_dim != expected_dim:
                raise ValueError(
                    f"Embedding 維度不符：預期 {expected_dim}，實際 {actual_dim}"
                )
            print(f"[*] 維度驗證通過: {actual_dim}")

    async def aretrieve(self, question: str) -> str:
        loop = asyncio.get_event_loop()
        # 採用 MMR (Maximal Marginal Relevance) 演算法，提升檢索結果的多樣性
        # fetch_k = k * 3 是經驗值，表示先撈出 3 倍數量的候選人，再從中挑選 k 個最多樣化的
        docs = await loop.run_in_executor(
            None,
            partial(
                self.vector_store.max_marginal_relevance_search,
                question,
                k=self.top_k,
                fetch_k=self.top_k * 3
            ),
        )
        context = "\n---\n".join([doc.page_content for doc in docs])
        if not context:
            return "此資料庫查無相關文件。"

        # 當 ui_type 非 TEXT 時，在尾部附加 metadata JSON
        ui_type = self.config.get("ui_type", "TEXT")
        if ui_type != "TEXT":
            metadata_list = [doc.metadata for doc in docs]
            metadata_block = json.dumps(
                {"ui_type": ui_type, "items": metadata_list},
                ensure_ascii=False,
            )
            context += UI_METADATA_DELIMITER + metadata_block

        return context
