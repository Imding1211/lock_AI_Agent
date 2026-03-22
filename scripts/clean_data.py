"""
清除所有測試資料，確保每次測試從乾淨狀態開始。

用法:
    python scripts/clean_data.py          # 清除全部
    python scripts/clean_data.py --pg     # 只清 PostgreSQL
    python scripts/clean_data.py --sqlite # 只清 SQLite
    python scripts/clean_data.py --profile # 只清 user profiles
"""

import os
import sys
import glob
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()


async def clean_postgres():
    """清除 PostgreSQL 資料（checkpointer、audit_log、user_facts）。"""
    pg_uri = os.getenv("POSTGRES_URI")
    if not pg_uri:
        print("[PostgreSQL] POSTGRES_URI 未設定，跳過")
        return

    try:
        from psycopg import AsyncConnection
        conn = await AsyncConnection.connect(pg_uri)

        for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs", "checkpoint_migrations"):
            await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

        await conn.execute("DROP TABLE IF EXISTS audit_log CASCADE")

        try:
            await conn.execute("DELETE FROM user_facts")
        except Exception:
            pass  # user_facts 表可能不存在

        await conn.commit()
        await conn.close()
        print("[PostgreSQL] 已清除: checkpointer tables, audit_log, user_facts data")
    except Exception as e:
        print(f"[PostgreSQL] 清除失敗: {e}")


def clean_sqlite():
    """清除 SQLite 檔案（chat_history.db、audit_log.db 及 WAL 檔）。"""
    removed = []
    for pattern in ("data/db/chat_history.db*", "data/db/audit_log.db*"):
        for f in glob.glob(pattern):
            os.remove(f)
            removed.append(f)

    if removed:
        print(f"[SQLite] 已清除: {', '.join(removed)}")
    else:
        print("[SQLite] 無檔案需要清除")


def clean_profiles():
    """清除 data/profiles/ 下所有使用者輪廓。"""
    removed = []
    for f in glob.glob("data/profiles/*.md"):
        os.remove(f)
        removed.append(os.path.basename(f))

    if removed:
        print(f"[Profiles] 已清除: {', '.join(removed)}")
    else:
        print("[Profiles] 無檔案需要清除")


async def clean_all():
    """清除全部測試資料。"""
    await clean_postgres()
    clean_sqlite()
    clean_profiles()


def main():
    args = set(sys.argv[1:])

    if not args:
        print("=== 清除所有測試資料 ===")
        asyncio.run(clean_all())
    else:
        if "--pg" in args:
            asyncio.run(clean_postgres())
        if "--sqlite" in args:
            clean_sqlite()
        if "--profile" in args:
            clean_profiles()

    print("=== 清除完成 ===")


if __name__ == "__main__":
    main()
