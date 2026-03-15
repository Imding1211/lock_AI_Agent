import os
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

_postgres_conn = None


async def build_postgres_saver(config: dict):
    global _postgres_conn
    uri = os.getenv(config.get("postgres_uri_env", "POSTGRES_URI"))
    print(f"[*] 初始化記憶體模組: 連線至 PostgreSQL")
    conn = await AsyncConnection.connect(
        uri, autocommit=True, prepare_threshold=0, row_factory=dict_row
    )
    _postgres_conn = conn
    saver = AsyncPostgresSaver(conn)
    await saver.setup()
    return saver


async def close_postgres_conn():
    global _postgres_conn
    if _postgres_conn is not None:
        await _postgres_conn.close()
        _postgres_conn = None
