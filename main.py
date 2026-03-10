# main.py
import logging
import warnings
import asyncio

logging.getLogger("curl_cffi").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message="Your application has authenticated using end user credentials")

from graph.builder import app

def _is_agent_step(item):
    """判斷 history item 是否為 agent 子圖步驟（格式：agent_name:agent_llm / agent_name:tool_node）"""
    parts = item.split(":", 1)
    return len(parts) == 2 and parts[1] in ("agent_llm", "tool_node")


def format_history_tree(history):
    """將扁平的 history list 轉成樹狀圖，自動去除子圖合併造成的重複"""

    # 1. 去重：主圖步驟只保留首次出現，agent 子步驟允許重複（LLM 可能多輪思考）
    seen = set()
    steps = []
    for item in history:
        if _is_agent_step(item) or item not in seen:
            steps.append(item)
            if not _is_agent_step(item):
                seen.add(item)

    # 2. 分組：將連續的 agent 子步驟收為一組
    blocks = []  # [(type, name, sub_steps | None)]
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
            blocks.append(("router", item.split(":", 1)[1], None))
            i += 1
        elif item == "topic_resolved":
            blocks.append(("flag", item, None))
            i += 1
        else:
            blocks.append(("node", item, None))
            i += 1

    # 3. 繪製樹狀圖
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
        elif btype == "flag":
            lines.append(f"{branch}🏁 {name}")
        else:
            lines.append(f"{branch}{name}")

    return "\n".join(lines)


async def run_test(query, thread_id="user_123"):
    print(f"\n======================================")
    print(f">>> [{thread_id}] 測試問題: {query}")

    inputs = {"question": query}
    config = {"configurable": {"thread_id": thread_id, "user_id": thread_id}}

    prev_state = await app.aget_state(config)
    prev_len = len(prev_state.values.get("history", [])) if prev_state.values else 0

    final = await app.ainvoke(inputs, config=config)

    current_history = final["history"][prev_len:]
    print(f"*** 最終結果 ***\n{final['answer']}")
    print(f"[路徑追蹤]\n{format_history_tree(current_history)}")
    print(f"======================================\n")

if __name__ == "__main__":
    async def main():
        print("\n" + "★"*50)
        print("系統功能展示（簡化架構 — 防抖移除 + 上下文工程）")
        print("★"*50)
        
        # ---------------------------------------------------------
        print("\n\n📍 【劇本 1】一般產品問題")
        print("展示重點：Router 分類到 product_expert，Agent 使用手冊資料庫檢索。")
        # ---------------------------------------------------------
        await run_test("門鎖的指紋要怎麼設定？", thread_id="demo_1")

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 2】對話記憶與追問")
        print("展示重點：跨回合記憶、Agent 主動追問設備資訊。")
        # ---------------------------------------------------------
        await run_test("那如果一直設定失敗怎麼辦？", thread_id="demo_1")
        await run_test("我是 Philips 的 Alpha", thread_id="demo_1")

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 3】模糊訊息 — Agent 主動追問")
        print("展示重點：不完整的訊息由 Agent 透過 prompt 自行判斷並追問，取代舊防抖反問。")
        # ---------------------------------------------------------
        await run_test("壞了", thread_id="demo_3")

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 4】問候語處理")
        print("展示重點：Agent 友善回應問候並詢問需要什麼協助。")
        # ---------------------------------------------------------
        await run_test("你好", thread_id="demo_4")

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 5】領域外問題 — LLM 生成拒絕")
        print("展示重點：out_of_domain 由 LLM 動態生成禮貌拒絕（非罐頭訊息）。")
        # ---------------------------------------------------------
        await run_test("今天台北天氣如何？", thread_id="demo_5")
        
        # ---------------------------------------------------------
        print("\n\n📍 【劇本 6】訂單查詢（API 工具）")
        print("展示重點：Router 分類到 order_clerk，Agent 自動使用 API 工具查詢。")
        # ---------------------------------------------------------
        await run_test("幫我查一下訂單 ORD-20260301 的出貨進度", thread_id="demo_6")
        
        # ---------------------------------------------------------
        print("\n\n📍 【劇本 7】網頁搜尋")
        print("展示重點：Router 分類到 web_researcher，Agent 使用網頁搜尋工具。")
        # ---------------------------------------------------------
        await run_test("市面上有哪些支援 Apple HomeKey 的電子鎖推薦？", thread_id="demo_7")

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 8】使用者輪廓建立")
        print("展示重點：從對話中萃取個人資訊存入輪廓，後續可自動帶入。")
        # ---------------------------------------------------------
        await run_test("我住在公寓大樓，用的是 Samsung SHP-DP609 指紋鎖，最近指紋辨識很不靈敏", thread_id="demo_8")

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 9】跨 Session 輪廓記憶")
        print("展示重點：不提品牌型號，系統透過輪廓提供個人化回覆。")
        # ---------------------------------------------------------
        await run_test("電池快沒電的時候會有什麼提示嗎？", thread_id="demo_8")

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 10】轉接真人客服")
        print("展示重點：使用者提供個資後要求轉接，自動帶入已知資訊。")
        # ---------------------------------------------------------
        await run_test("我住在台北市信義區松仁路 100 號 12 樓，電話 0912-345-678，門鎖打不開", thread_id="demo_10")
        await run_test("沒辦法解決，幫我轉接真人客服", thread_id="demo_10")

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 11】輪廓預填設備資訊")
        print("展示重點：從輪廓自動補充品牌型號，Agent 不重複詢問，直接檢索。")
        # ---------------------------------------------------------
        await run_test("指紋辨識又失靈了，怎麼辦？", thread_id="demo_8")

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 12】長文多意圖偵測")
        print("展示重點：使用者一次傳送包含多個意圖的長訊息，Router 判斷主要意圖。")
        # ---------------------------------------------------------
        await run_test(
            "你好，我上週買了一台 Philips Alpha 電子鎖，安裝師傅裝好之後指紋一直設定不成功，"
            "我試了很多次都沒辦法，而且我還想順便問一下我的訂單 ORD-20260301 到底出貨了沒有，"
            "如果還是不行的話我可能要請你們派人來看一下",
            thread_id="demo_12"
        )

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 13】長文多意圖 — 偏向訂單查詢")
        print("展示重點：長訊息中主要意圖為訂單查詢。")
        # ---------------------------------------------------------
        await run_test(
            "我之前訂了兩台電子鎖，一台是給我家大門用的，另一台是要裝在辦公室，"
            "但是到現在只收到一台，訂單編號是 ORD-20260215，麻煩幫我查一下另一台的出貨進度，"
            "另外那台已經裝好的有時候會發出嗶嗶聲不知道是什麼意思",
            thread_id="demo_13"
        )

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 14】長文多意圖 — 夾雜領域外話題")
        print("展示重點：長訊息中夾雜與電子鎖無關的內容，Agent 聚焦回答領域內部分。")
        # ---------------------------------------------------------
        await run_test(
            "最近天氣好熱喔冷氣都不夠涼，對了我家那台電子鎖密碼好像被我改過之後忘記了，"
            "現在只能用指紋開門，請問要怎麼重設密碼啊？還有你們週末有營業嗎？",
            thread_id="demo_14"
        )
        

    asyncio.run(main())
