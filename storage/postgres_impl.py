import os
from datetime import datetime, timezone
from psycopg import AsyncConnection

_postgres_conn = None


class PostgresAuditStorage:
    def __init__(self, conn: AsyncConnection):
        self._conn = conn

    async def log_message(self, user_id: str, role: str, content: str):
        timestamp = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "INSERT INTO audit_log (user_id, role, content, timestamp) VALUES (%s, %s, %s, %s)",
            (user_id, role, content, timestamp),
        )
        await self._conn.commit()


async def build_postgres_storage(config: dict) -> PostgresAuditStorage:
    global _postgres_conn
    uri = os.getenv(config.get("postgres_uri_env", "POSTGRES_URI"))
    print(f"[*] 初始化審計日誌模組: 連線至 PostgreSQL")
    conn = await AsyncConnection.connect(uri)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL
        )
    """)
    await conn.commit()
    _postgres_conn = conn
    return PostgresAuditStorage(conn)


async def close_postgres_storage():
    global _postgres_conn
    if _postgres_conn is not None:
        await _postgres_conn.close()
        _postgres_conn = None
