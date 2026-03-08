from langgraph.checkpoint.memory import MemorySaver

def get_checkpointer(config: dict):
    memory_type = config.get("type", "memory")
    
    print(f"[*] 初始化記憶體模組: 使用 {memory_type} 機制...")
    
    if memory_type == "memory":
        return MemorySaver()
        
    elif memory_type == "sqlite":
        # 未來你想支援 SQLite 時，只需要安裝 langgraph-checkpoint-sqlite 
        # 然後把下面這幾行註解打開，就可以無縫支援了！
        # from langgraph.checkpoint.sqlite import SqliteSaver
        # db_path = config.get("path", "./chat_history.db")
        # return SqliteSaver.from_conn_string(db_path)
        raise NotImplementedError("SQLite 模組尚未實作。")
        
    elif memory_type == "postgres":
        # 未來支援 PostgreSQL 的擴充點
        raise NotImplementedError("PostgreSQL 模組尚未實作。")
        
    else:
        raise ValueError(f"不支援的記憶體類型: {memory_type}")