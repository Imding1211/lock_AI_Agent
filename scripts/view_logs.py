"""查看 audit_log 表中的對話紀錄。

用法：
    python scripts/view_logs.py              # 顯示最近 30 則紀錄
    python scripts/view_logs.py 50           # 顯示最近 50 則紀錄
    python scripts/view_logs.py --user {id}  # 查看特定使用者
"""

import os
import sys
import asyncio
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()


def format_timestamp(ts):
    """格式化時間戳"""
    if ts is None:
        return "—"
    try:
        if isinstance(ts, datetime):
            return ts.strftime("%Y-%m-%d %H:%M:%S")
        return str(ts)[:19]
    except Exception:
        return str(ts)


async def view_logs(limit=30, user_id=None):
    pg_uri = os.getenv("POSTGRES_URI")
    if not pg_uri:
        print("\n[錯誤] 環境變數 POSTGRES_URI 未設定。")
        print("請確認 .env 檔案中已設定 POSTGRES_URI。")
        return

    try:
        from psycopg import AsyncConnection

        conn = await AsyncConnection.connect(pg_uri)

        # 確保表存在（與 postgres_impl.py 結構一致）
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

        if user_id:
            query = (
                "SELECT id, user_id, role, content, timestamp "
                "FROM audit_log WHERE user_id = %s "
                "ORDER BY id DESC LIMIT %s"
            )
            params = (user_id, limit)
        else:
            query = (
                "SELECT id, user_id, role, content, timestamp "
                "FROM audit_log "
                "ORDER BY id DESC LIMIT %s"
            )
            params = (limit,)

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        await conn.close()

        if not rows:
            print("\n[!] 目前尚無任何對話紀錄。")
            return

        user_label = f" — 使用者: {user_id}" if user_id else ""
        print(f"\n{'='*120}")
        print(f"  Audit Log — 最近 {limit} 則{user_label}")
        print(f"{'='*120}")
        print(f"{'ID':<6} | {'User ID':<20} | {'時間':<20} | {'角色':<10} | {'內容'}")
        print(f"{'-'*120}")

        # 反轉順序，讓最新的在最下面顯示，符合閱讀習慣
        for row in reversed(rows):
            rid, uid, role, content, ts = row

            # 根據角色選擇圖標
            if role == "user_raw":
                role_icon = "📩 [RAW] "
                color_start = "\033[90m"  # 灰色
            elif role == "user":
                role_icon = "👤 [USER]"
                color_start = "\033[94m"  # 藍色
            elif role == "ai":
                role_icon = "🤖 [AI]  "
                color_start = "\033[92m"  # 綠色
            else:
                role_icon = f"❓ [{role}]"
                color_start = ""

            color_end = "\033[0m"

            # 處理內容換行，保持排版整齊
            content_lines = content.strip().split('\n')
            first_line = content_lines[0]

            print(f"{rid:<6} | {uid:<20} | {format_timestamp(ts):<20} | {color_start}{role_icon}{color_end} | {first_line}")

            # 如果內容有多行，進行縮排顯示
            if len(content_lines) > 1:
                for line in content_lines[1:]:
                    print(f"{' ':<6} | {' ':<20} | {' ':<20} | {' ':<10} | {line}")

        print(f"{'='*120}")
        print(f">>> 共顯示最近 {len(rows)} 則紀錄。")

    except Exception as e:
        if "audit_log" in str(e) and "does not exist" in str(e):
            print("\n[錯誤] audit_log 表不存在。")
            print("請確認系統已啟動過並建立了 audit_log 表。")
        else:
            print(f"\n[錯誤] 發生意外：{e}")


if __name__ == "__main__":
    limit = 30
    target_user = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--user" and i + 1 < len(args):
            target_user = args[i + 1]
            i += 2
        else:
            try:
                limit = int(args[i])
            except ValueError:
                pass
            i += 1

    asyncio.run(view_logs(limit=limit, user_id=target_user))
