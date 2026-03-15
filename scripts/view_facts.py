"""查看 user_facts 表中的使用者硬事實記錄。

用法：
    python scripts/view_facts.py                  # 顯示所有使用者的當前事實
    python scripts/view_facts.py --all             # 顯示所有記錄（含歷史）
    python scripts/view_facts.py --user {user_id}  # 查看特定使用者
    python scripts/view_facts.py --user {user_id} --all  # 特定使用者含歷史
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


async def view_facts(user_id=None, show_all=False):
    pg_uri = os.getenv("POSTGRES_URI")
    if not pg_uri:
        print("\n[錯誤] 環境變數 POSTGRES_URI 未設定。")
        print("請確認 .env 檔案中已設定 POSTGRES_URI。")
        return

    try:
        from psycopg import AsyncConnection

        conn = await AsyncConnection.connect(pg_uri)

        # 組裝查詢
        if user_id and show_all:
            query = (
                "SELECT id, user_id, attr_key, attr_val, is_current, start_date, end_date "
                "FROM user_facts WHERE user_id = %s "
                "ORDER BY attr_key, start_date DESC"
            )
            params = (user_id,)
        elif user_id:
            query = (
                "SELECT id, user_id, attr_key, attr_val, is_current, start_date, end_date "
                "FROM user_facts WHERE user_id = %s AND is_current = TRUE "
                "ORDER BY attr_key"
            )
            params = (user_id,)
        elif show_all:
            query = (
                "SELECT id, user_id, attr_key, attr_val, is_current, start_date, end_date "
                "FROM user_facts "
                "ORDER BY user_id, attr_key, start_date DESC"
            )
            params = None
        else:
            query = (
                "SELECT id, user_id, attr_key, attr_val, is_current, start_date, end_date "
                "FROM user_facts WHERE is_current = TRUE "
                "ORDER BY user_id, attr_key"
            )
            params = None

        if params:
            cursor = await conn.execute(query, params)
        else:
            cursor = await conn.execute(query)
        rows = await cursor.fetchall()
        await conn.close()

        if not rows:
            if user_id:
                print(f"\n[!] 使用者 {user_id} 目前尚無任何事實記錄。")
            else:
                print("\n[!] 目前尚無任何事實記錄。")
            return

        # 顯示表頭
        mode_label = "全部記錄（含歷史）" if show_all else "當前有效記錄"
        user_label = f" — 使用者: {user_id}" if user_id else ""
        print(f"\n{'='*120}")
        print(f"  User Facts — {mode_label}{user_label}")
        print(f"{'='*120}")
        print(f"{'ID':<5} | {'User ID':<20} | {'屬性':<15} | {'值':<30} | {'狀態':<8} | {'生效時間':<20} | {'失效時間':<20}")
        print(f"{'-'*120}")

        current_user = None
        for rid, uid, key, val, is_current, start, end in rows:
            # 使用者分隔線
            if uid != current_user:
                if current_user is not None:
                    print(f"{'-'*120}")
                current_user = uid

            # 狀態標記與顏色
            if is_current:
                status = "CURRENT"
                color_start = "\033[92m"  # 綠色
            else:
                status = "EXPIRED"
                color_start = "\033[90m"  # 灰色

            color_end = "\033[0m"

            start_str = format_timestamp(start)
            end_str = format_timestamp(end)

            print(
                f"{rid:<5} | {uid:<20} | {key:<15} | {val:<30} | "
                f"{color_start}{status:<8}{color_end} | {start_str:<20} | {end_str:<20}"
            )

        print(f"{'='*120}")
        print(f">>> 共顯示 {len(rows)} 筆記錄。")

        # 統計摘要
        if not user_id:
            user_count = len(set(r[1] for r in rows))
            current_count = sum(1 for r in rows if r[4])
            expired_count = sum(1 for r in rows if not r[4])
            print(f">>> 涵蓋 {user_count} 位使用者，{current_count} 筆有效 / {expired_count} 筆歷史。")

    except Exception as e:
        if "user_facts" in str(e) and "does not exist" in str(e):
            print("\n[錯誤] user_facts 表不存在。")
            print("請先建立表結構，參考 docs/manuals/系統部署與環境架設指南.md。")
        else:
            print(f"\n[錯誤] 發生意外：{e}")


if __name__ == "__main__":
    target_user = None
    show_all = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--user" and i + 1 < len(args):
            target_user = args[i + 1]
            i += 2
        elif args[i] == "--all":
            show_all = True
            i += 1
        else:
            # 第一個無旗標參數當作 user_id
            target_user = args[i]
            i += 1

    asyncio.run(view_facts(user_id=target_user, show_all=show_all))
