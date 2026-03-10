from langgraph.checkpoint.memory import MemorySaver

# 保存 aiosqlite 連線參考，供程式結束時關閉
_sqlite_conn = None

async def get_checkpointer(config: dict):
    global _sqlite_conn
    memory_type = config.get("type", "memory")

    print(f"[*] 初始化記憶體模組: 使用 {memory_type} 機制...")

    if memory_type == "memory":
        return MemorySaver()

    elif memory_type == "sqlite":
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        db_path = config.get("path", "./chat_history.db")
        conn = await aiosqlite.connect(db_path)
        _sqlite_conn = conn
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        return saver

    elif memory_type == "postgres":
        # 未來支援 PostgreSQL 的擴充點
        raise NotImplementedError("PostgreSQL 模組尚未實作。")

    else:
        raise ValueError(f"不支援的記憶體類型: {memory_type}")

async def close_checkpointer():
    """關閉 aiosqlite 連線，避免背景線程卡住"""
    global _sqlite_conn
    if _sqlite_conn is not None:
        await _sqlite_conn.close()
        _sqlite_conn = None
