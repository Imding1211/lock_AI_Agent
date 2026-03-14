import sqlite3
import json

def check_db():
    db_path = "data/db/chat_history.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print(f"Checking {db_path}...")
    cursor.execute("SELECT thread_id, checkpoint FROM checkpoints ORDER BY checkpoint_id DESC LIMIT 5")
    rows = cursor.fetchall()
    
    for thread_id, checkpoint_raw in rows:
        import pickle
        checkpoint = pickle.loads(checkpoint_raw)
        channel_values = checkpoint.get("channel_values", {})
        history = channel_values.get("history", [])
        msgs = channel_values.get("messages", [])
        print(f"Thread: {thread_id}")
        print(f"  History length: {len(history)}")
        print(f"  Messages length: {len(msgs)}")
        if history:
            print(f"  Last history items: {history[-5:]}")
            
    conn.close()

if __name__ == "__main__":
    check_db()
