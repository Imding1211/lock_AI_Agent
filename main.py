# main.py
import os
import glob
import logging
import warnings
import asyncio

logging.getLogger("curl_cffi").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message="Your application has authenticated using end user credentials")

from graph.builder import build_graph
from memory import close_checkpointer


def clean_test_data():
    """清除測試資料，確保每次測試從乾淨狀態開始。"""
    removed = []

    # 清除對話記憶 DB
    for db in ("data/db/chat_history.db", "data/db/audit_log.db"):
        if os.path.exists(db):
            os.remove(db)
            removed.append(db)

    # 清除使用者輪廓
    for f in glob.glob("data/profiles/*.md"):
        os.remove(f)
        removed.append(f)

    if removed:
        print(f"[清除] 已刪除 {len(removed)} 個檔案: {', '.join(removed)}")
    else:
        print("[清除] 無需清除，已是乾淨狀態")


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

    # 給予 SQLite 寫入事務足夠的完成時間，避免讀寫競爭
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
        clean_test_data()
        app = await build_graph()
        T = "demo"  # 共用 thread，測試跨回合記憶 + 摘要壓縮
        
        # --- 第 1 輪：產品問題 → product_expert + manage_memory:skip ---
        await run_test(app, "我的 Philips Alpha 指紋怎麼設定？", thread_id=T, show_memory=True)
        """
        # --- 第 2 輪：故障排除 → troubleshooter（累積 messages）---
        await run_test(app, "指紋辨識不靈敏，按好幾次才能開門", thread_id=T, show_memory=True)

        # --- 第 3 輪：追問 → troubleshooter（預期觸發 manage_memory:summarized）---
        await run_test(app, "清潔過感應區了還是一樣", thread_id=T, show_memory=True)

        # --- 第 4 輪：換話題 → product_expert（驗證摘要注入 [前情提要]）---
        await run_test(app, "電池快沒電會有什麼提示嗎？", thread_id=T, show_memory=True)

        # --- 領域外問題 → out_of_domain ---
        await run_test(app, "今天台北天氣如何？", thread_id="demo_ood")

        # --- 多意圖平行派發 → order_clerk + web_researcher ---
        await run_test(app,
            "幫我查訂單 ORD-20260301 的進度，另外有推薦支援 HomeKey 的電子鎖嗎？",
            thread_id="demo_multi"
        )

        # --- 轉接真人 → transfer_human（帶入輪廓資訊）---
        await run_test(app,
            "我住台北市信義區松仁路 100 號 12 樓，電話 0912-345-678，幫我轉接真人客服",
            thread_id="demo_human"
        )
        
        # --- 敏感詞護欄 → guardrail_triggered（跳過 LLM，強制轉接真人）---
        await run_test(app,
            "這款電子鎖多少錢？可以報價嗎？",
            thread_id="demo_guardrail"
        )
        """


        # --- SQLite 持久化驗證 ---
        print("=" * 40)
        db_path = "./data/db/chat_history.db"
        if os.path.exists(db_path):
            print(f"[SQLite] {db_path} = {os.path.getsize(db_path):,} bytes")

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
        
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(close_checkpointer(), timeout=10)
        except asyncio.TimeoutError:
            print("[警告] close_checkpointer 超時，強制結束")
        
    asyncio.run(main())
