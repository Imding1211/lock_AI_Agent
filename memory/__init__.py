from langgraph.checkpoint.memory import MemorySaver
from .sqlite_saver import build_sqlite_saver, close_sqlite_conn
from .postgres_saver import build_postgres_saver, close_postgres_conn

MEMORY_REGISTRY = {
    "sqlite": build_sqlite_saver,
    "postgres": build_postgres_saver,
}

_checkpointer_type = None

async def get_checkpointer(config: dict):
    global _checkpointer_type
    memory_type = config.get("type", "memory")
    _checkpointer_type = memory_type
    print(f"[*] 初始化記憶體模組: 使用 {memory_type} 機制...")

    if memory_type == "memory":
        return MemorySaver()

    builder = MEMORY_REGISTRY.get(memory_type)
    if not builder:
        raise ValueError(f"不支援的記憶體類型: {memory_type}，可用: memory, {', '.join(MEMORY_REGISTRY)}")
    return await builder(config)

async def close_checkpointer():
    if _checkpointer_type == "postgres":
        await close_postgres_conn()
    else:
        await close_sqlite_conn()
