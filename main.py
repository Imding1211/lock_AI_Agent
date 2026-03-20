# main.py
import os
import glob
import logging
import warnings
import asyncio

logging.getLogger("curl_cffi").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message="Your application has authenticated using end user credentials")

from dotenv import load_dotenv
load_dotenv()

from graph.builder import build_graph
from memory import close_checkpointer
from core.config import USER_PROFILE_CONFIG
from profiles import ProfileManager, init_facts_db, close_facts_db


async def clean_test_data():
    """清除測試資料，確保每次測試從乾淨狀態開始。"""
    cleaned = []

    # 清除 PostgreSQL 資料（若有連線）
    pg_uri = os.getenv("POSTGRES_URI")
    if pg_uri:
        try:
            from psycopg import AsyncConnection
            conn = await AsyncConnection.connect(pg_uri)
            # 清除 checkpointer 表（langgraph-checkpoint-postgres 建立的表）
            for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs", "checkpoint_migrations"):
                await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            # 清除審計日誌表
            await conn.execute("DROP TABLE IF EXISTS audit_log CASCADE")
            # 清除 user_facts 資料（保留表結構）
            await conn.execute("DELETE FROM user_facts")
            await conn.commit()
            await conn.close()
            cleaned.append("PostgreSQL tables + user_facts data")
        except Exception as e:
            print(f"[清除] PostgreSQL 清除失敗: {e}")

    # 清除 SQLite 檔案（回退模式）
    for db in ("data/db/chat_history.db", "data/db/audit_log.db"):
        if os.path.exists(db):
            os.remove(db)
            cleaned.append(db)

    # 清除使用者輪廓
    for f in glob.glob("data/profiles/*.md"):
        os.remove(f)
        cleaned.append(f)

    if cleaned:
        print(f"[清除] 已清除: {', '.join(cleaned)}")
    else:
        print("[清除] 無需清除，已是乾淨狀態")


async def show_user_facts(user_id: str):
    """查詢並顯示指定使用者的 user_facts。"""
    pg_uri = os.getenv("POSTGRES_URI")
    if not pg_uri:
        print(f"[Facts] POSTGRES_URI 未設定，跳過")
        return
    try:
        from psycopg import AsyncConnection
        conn = await AsyncConnection.connect(pg_uri)
        cursor = await conn.execute(
            "SELECT attr_key, attr_val, is_current, start_date, end_date "
            "FROM user_facts WHERE user_id = %s ORDER BY attr_key, start_date DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        await conn.close()

        if not rows:
            print(f"[Facts] {user_id}: (無記錄)")
            return

        print(f"[Facts] {user_id}:")
        for key, val, is_current, start, end in rows:
            status = "CURRENT" if is_current else "EXPIRED"
            end_str = str(end)[:19] if end else "—"
            print(f"  {key:<15} = {val:<30} [{status}] {str(start)[:19]} ~ {end_str}")
    except Exception as e:
        print(f"[Facts] 查詢失敗: {e}")


def _is_agent_step(item):
    parts = item.split(":", 1)
    return len(parts) == 2 and parts[1] in ("agent_llm", "tool_node")


def format_history_tree(history):
    seen = set()
    steps = []
    for item in history:
        if _is_agent_step(item) or item not in seen:
            steps.append(item)
            if not _is_agent_step(item):
                seen.add(item)

    blocks = []
    i = 0
    while i < len(steps):
        item = steps[i]
        if _is_agent_step(item):
            agent = item.split(":", 1)[0]
            subs = []
            while i < len(steps) and _is_agent_step(steps[i]) and steps[i].split(":", 1)[0] == agent:
                subs.append(steps[i].split(":", 1)[1])
                i += 1
            blocks.append(("agent", agent, subs))
        elif item.startswith("router:"):
            router_label = item.split(":", 1)[1]
            if not blocks or blocks[-1][0] != "router" or blocks[-1][1] != router_label:
                blocks.append(("router", router_label, None))
            i += 1
        elif item.startswith("manage_memory:"):
            blocks.append(("memory", item.split(":", 1)[1], None))
            i += 1
        elif item in ("topic_resolved", "guardrail_triggered"):
            blocks.append(("flag", item, None))
            i += 1
        else:
            blocks.append(("node", item, None))
            i += 1

    lines = []
    for idx, (btype, name, subs) in enumerate(blocks):
        is_last = idx == len(blocks) - 1
        branch = "└── " if is_last else "├── "
        indent = "    " if is_last else "│   "

        if btype == "agent":
            lines.append(f"{branch}{name}")
            for j, sub in enumerate(subs):
                sub_branch = "└── " if j == len(subs) - 1 else "├── "
                lines.append(f"{indent}{sub_branch}{sub}")
        elif btype == "router":
            lines.append(f"{branch}router → {name}")
        elif btype == "memory":
            lines.append(f"{branch}manage_memory → {name}")
        elif btype == "flag":
            lines.append(f"{branch}[FLAG] {name}")
        else:
            lines.append(f"{branch}{name}")

    return "\n".join(lines)


async def run_test(app, query, thread_id="user_123", show_memory=False):
    print(f"\n>>> [{thread_id}] {query}")

    inputs = {"question": query}
    config = {"configurable": {"thread_id": thread_id, "user_id": thread_id}}

    try:
        prev_state = await asyncio.wait_for(app.aget_state(config), timeout=10)
        prev_len = len(prev_state.values.get("history", [])) if prev_state.values else 0
    except asyncio.TimeoutError:
        prev_len = 0

    final = await app.ainvoke(inputs, config=config)

    # 給予資料庫寫入事務足夠的完成時間，避免讀寫競爭
    await asyncio.sleep(0.5)

    raw_history = final.get("history", [])
    current_history = raw_history[prev_len:]

    print(f"[回覆] {final.get('answer', '(無回覆)')}")

    try:
        path_tree = format_history_tree(current_history)
        print(f"[路徑]\n{path_tree}")
    except Exception as e:
        print(f"[路徑] (路徑解析失敗: {e})")
        print(f"原始數據: {current_history}")

    if show_memory:
        try:
            state = await asyncio.wait_for(app.aget_state(config), timeout=10)
            vals = state.values or {}
            msgs = vals.get("messages", [])
            summary = vals.get("summary", "")
            print(f"[記憶] messages={len(msgs)}, summary={len(summary)}字")
            if summary:
                print(f"[摘要] {summary[:15]}...")
        except asyncio.TimeoutError:
            print("[記憶] (aget_state 超時，跳過)")

    print()


if __name__ == "__main__":
    async def main():
        await clean_test_data()

        # 初始化 Facts DB
        if USER_PROFILE_CONFIG.get("facts_enabled", False):
            await init_facts_db(USER_PROFILE_CONFIG)

        app = await build_graph()
        T = "demo"  # 共用 thread，測試跨回合記憶 + 摘要壓縮

        # ============================================================
        # A. 共用 thread "demo"：跨回合記憶 + 摘要壓縮
        # ============================================================

        # --- 第 1 輪：db_video / troubleshoot (V-T1) → facts 寫入 device_brand ---
        await run_test(app, "Dormakaba 鎖舌卡住怎麼處理？", thread_id=T, show_memory=True)
        await show_user_facts(T)

        # --- 第 2 輪：db_video / setup (V-S1) → 累積 messages ---
        await run_test(app, "Chainlock 怎麼進入設定模式？", thread_id=T, show_memory=True)

        # --- 第 3 輪：db_line_chat / troubleshoot (L-T2) → 預期觸發 manage_memory:summarized ---
        await run_test(app, "門把按下去不會彈回來是什麼問題？可以維修嗎？", thread_id=T, show_memory=True)

        # --- 第 4 輪：db_video / knowledge (V-K3) → 換話題，驗證摘要注入 [前情提要] ---
        await run_test(app, "推拉式和把手式電子鎖差在哪？", thread_id=T, show_memory=True)

        # ============================================================
        # B. db_youtube 專用 thread：驗證 HyDE + Small-to-Big + 時間戳
        # ============================================================

        # --- Y-S3：家庭成員邀請設定 ---
        await run_test(app, "請問怎麼把我的家人加入 Chatlock AI-99 的 App 裡面讓他也能開門？", thread_id="demo_YT", show_memory=True)

        # --- Y-K1：追問解除綁定差異（同 thread 測跨回合） ---
        await run_test(app, "解除綁定和解綁並清除數據有什麼差別？", thread_id="demo_YT", show_memory=True)

        # ============================================================
        # C. 個別 thread：特殊流程驗證
        # ============================================================

        # --- 領域外問題 → out_of_domain ---
        await run_test(app, "今天台北天氣如何？", thread_id="demo_ood")

        # --- 多意圖平行派發 → order_clerk + product_expert ---
        await run_test(app,
            "幫我查訂單 ORD-20260301 的進度，另外 FAMMIX SAFER-2 電子鎖有哪些解鎖功能？",
            thread_id="demo_multi"
        )

        # --- 轉接真人（含個資）→ transfer_human + facts 寫入 ---
        await run_test(app,
            "我住台北市信義區松仁路 100 號 12 樓，電話 0912-345-678，幫我轉接真人客服",
            thread_id="demo_human"
        )
        await show_user_facts("demo_human")

        # --- 敏感詞護欄 → guardrail_triggered（跳過 LLM，強制轉接真人）---
        # 改用 L-K1 風格的價格詢問，測試金錢意圖攔截
        await run_test(app,
            "有網路功能的電子鎖大概多少錢？可以報價嗎？",
            thread_id="demo_guardrail"
        )

        # --- SCD Type 2 驗證：更新地址，確認舊記錄 EXPIRED ---
        await run_test(app,
            "我搬家了，新地址是新北市板橋區文化路一段 200 號 5 樓",
            thread_id="demo_human"
        )
        await show_user_facts("demo_human")

        # --- 轉接真人（驗證 SQL facts 優先填入表單）---
        await run_test(app,
            "我要找真人客服，請幫我轉接真人",
            thread_id="demo_human"
        )

        # --- 持久化驗證 ---
        print("=" * 40)

        config = {"configurable": {"thread_id": T, "user_id": T}}
        try:
            state = await asyncio.wait_for(app.aget_state(config), timeout=10)
            if state.values:
                msgs = state.values.get("messages", [])
                summary = state.values.get("summary", "")
                print(f"[最終] thread={T}, messages={len(msgs)}, summary={len(summary)}字")
                if summary:
                    print(f"[摘要] {summary}")
        except asyncio.TimeoutError:
            print("[警告] 最終 aget_state 超時，跳過")

        # 顯示所有測試使用者的 facts
        print("\n" + "=" * 40)
        print("[Facts 總覽]")
        for uid in (T, "demo_YT", "demo_human", "demo_ood", "demo_multi", "demo_guardrail"):
            await show_user_facts(uid)

        await asyncio.sleep(0.5)
        await close_facts_db()
        try:
            await asyncio.wait_for(close_checkpointer(), timeout=10)
        except asyncio.TimeoutError:
            print("[警告] close_checkpointer 超時，強制結束")

    asyncio.run(main())
