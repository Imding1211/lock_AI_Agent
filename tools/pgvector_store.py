import asyncio
import os
from functools import partial
from langchain_postgres import PGVector
from .base_retriever import BaseRetriever

from embeddings import get_embedding


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
        docs = await loop.run_in_executor(
            None,
            partial(self.vector_store.similarity_search, question, k=self.top_k),
        )
        context = "\n---\n".join([doc.page_content for doc in docs])
        return context if context else "此資料庫查無相關文件。"
