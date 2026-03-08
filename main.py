# main.py
import logging
import asyncio

logging.getLogger("curl_cffi").setLevel(logging.ERROR)

from graph.builder import app

async def run_test(query, thread_id="user_123", pre_intent=None):
    print(f"\n======================================")
    print(f">>> [{thread_id}] 測試問題: {query}")
    if pre_intent:
        print(f">>> [預判意圖] {pre_intent}")

    inputs = {"question": query, "standalone_query": "", "context": "", "answer": "", "intent": "", "slots": {}}
    if pre_intent:
        inputs["intent"] = pre_intent
    config = {"configurable": {"thread_id": thread_id}}

    final = await app.ainvoke(inputs, config=config)

    print(f"*** 最終結果 ***\n{final['answer']}")
    print(f"\n[目前收集到的資訊]: {final.get('slots', {})}")
    print(f"[路徑追蹤]: {' -> '.join(final['history'])}")
    print(f"======================================\n")

if __name__ == "__main__":
    async def main():
        print("\n" + "★"*50)
        print("系統功能展示")
        print("★"*50)
        
        # ---------------------------------------------------------
        print("\n\n📍 【劇本 1】對話記憶與主動追問 (Slot Filling)")
        print("展示重點：跨回合記憶、指代還原 (Query Rewrite)、發現缺少資訊並反問。")
        # ---------------------------------------------------------
        await run_test("門鎖的指紋要怎麼設定？", thread_id="demo_1")
        """
        # 系統會將問題改寫為「指紋一直設定失敗怎麼辦？」，接著發現沒有品牌型號，發動反問
        await run_test("那如果一直設定失敗怎麼辦？", thread_id="demo_1") 
        # 使用者補齊資訊，系統成功存入 slots，並給出特定型號的故障排除
        await run_test("我是 Philips 的 Alpha", thread_id="demo_1") 

        
        # ---------------------------------------------------------
        print("\n\n📍 【劇本 2】優雅降級 (不知道型號) 與主動轉接真人")
        print("展示重點：辨識 UNKNOWN 狀態、給予通用解答、主動詢問轉接意願。")
        # ---------------------------------------------------------
        await run_test("密碼面板按了都沒反應", thread_id="demo_2")
        # 使用者放棄治療，系統捕捉到 UNKNOWN，不強迫追問，給予通用解法並詢問是否轉接
        await run_test("我不清楚型號跟品牌，盒子早丟了", thread_id="demo_2") 
        # 系統精準捕捉 transfer_human 意圖，直接導向 human 節點
        await run_test("對，這些方法都沒用，請幫我轉接客服", thread_id="demo_2") 

        
        # ---------------------------------------------------------
        print("\n\n📍 【劇本 3】意圖空降 (Semantic Routing)")
        print("展示重點：跳過手冊庫，直接呼叫 API 節點。")
        # ---------------------------------------------------------
        await run_test("幫我查一下我的訂單進度", thread_id="demo_3")

        
        # ---------------------------------------------------------
        print("\n\n📍 【劇本 4】領域護欄 (Domain Guardrail) 發威")
        print("展示重點：嚴格遵守設定檔的 Domain，拒絕回答網頁搜尋到的無關內容。")
        # ---------------------------------------------------------
        # DuckDuckGo 一定查得到天氣，但 Grader 會因為「不符合電子鎖領域」嚴格回傳 NO，最後轉接真人
        await run_test("今天台北天氣如何？", thread_id="demo_4") 


        # ---------------------------------------------------------
        print("\n\n📍 【劇本 5】網頁搜尋救援 (Fallback Chain)")
        print("展示重點：內部資料庫查無結果，但問題符合領域，交由網頁搜尋救援成功。")
        # ---------------------------------------------------------
        # 手冊與故障庫可能沒有，一路降級到 Web Search，因為符合電子鎖領域，Grader 放行
        await run_test("市面上有哪些支援 Apple HomeKey 的電子鎖推薦？", thread_id="demo_5")
        

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 6】使用者輪廓 — 首次建立與個人化回覆")
        print("展示重點：首次對話時載入空輪廓，對話結束後萃取個人資訊並存入輪廓檔案。")
        # ---------------------------------------------------------
        # 使用者主動提及品牌型號和居住環境，系統應萃取並存入輪廓
        await run_test("我住在公寓大樓，用的是 Samsung SHP-DP609 指紋鎖，最近指紋辨識很不靈敏", thread_id="demo_6")


        # ---------------------------------------------------------
        print("\n\n📍 【劇本 7】使用者輪廓 — 跨 Session 記憶驗證")
        print("展示重點：不再提及品牌型號，但系統透過已載入的輪廓仍能提供個人化回覆。")
        # ---------------------------------------------------------
        # 不提品牌型號，但 load_user_profile 會載入劇本 6 存下的輪廓
        # 系統應能根據背景資訊（Samsung SHP-DP609）給出針對性回覆
        await run_test("電池快沒電的時候會有什麼提示嗎？", thread_id="demo_6")

        
        # ---------------------------------------------------------
        print("\n\n📍 【劇本 8】轉真人時自動帶入個人資訊")
        print("展示重點：轉接真人時，自動帶入輪廓中已有的地址、電話等，僅請使用者補充缺失欄位並確認。")
        # ---------------------------------------------------------
        # 第一輪：使用者提供地址電話，系統萃取存入輪廓
        await run_test("我住在台北市信義區松仁路 100 號 12 樓，電話 0912-345-678，門鎖打不開", thread_id="demo_8")
        # 第二輪：要求轉接真人，系統應帶入已知的地址和電話，請使用者補充缺失資訊
        await run_test("沒辦法解決，幫我轉接真人客服", thread_id="demo_8")
        

        # ---------------------------------------------------------
        print("\n\n📍 【劇本 9】Slots 預填與衝突處理")
        print("展示重點：從使用者輪廓預填 slots（品牌型號），不再追問已知資訊，直接進入檢索。")
        # ---------------------------------------------------------
        # 用 demo_6 的既有輪廓（Samsung SHP-DP609），觸發 troubleshooting 意圖
        # 系統應從輪廓預填品牌型號，不再走 ask_missing_slots，直接進檢索
        await run_test("指紋辨識又失靈了，怎麼辦？", thread_id="demo_6")

        
        # ---------------------------------------------------------
        print("\n\n📍 【劇本 10】LLM 防抖預判意圖 — 跳過 detect_intent")
        print("展示重點：帶入 pre_intent，detect_intent 節點應直接沿用，不再呼叫 LLM。")
        # ---------------------------------------------------------
        # 模擬防抖階段已預判為 troubleshooting，路徑追蹤應顯示 detect_intent(pre-detected)
        await run_test("指紋辨識失靈怎麼辦？", thread_id="demo_10", pre_intent="troubleshooting")


        # ---------------------------------------------------------
        print("\n\n📍 【劇本 11】LLM 防抖預判意圖 — 訂單查詢直達 API")
        print("展示重點：pre_intent=order_status，跳過 detect_intent 直達 API 檢索節點。")
        # ---------------------------------------------------------
        await run_test("幫我查訂單進度", thread_id="demo_11", pre_intent="order_status")


        # ---------------------------------------------------------
        print("\n\n📍 【劇本 12】LLM 防抖預判意圖 — 轉接真人")
        print("展示重點：pre_intent=transfer_human，跳過 detect_intent 直達 human 節點。")
        # ---------------------------------------------------------
        await run_test("轉接客服", thread_id="demo_12", pre_intent="transfer_human")


        # ---------------------------------------------------------
        print("\n\n📍 【劇本 13】LLM 防抖預判意圖 — 領域外問題")
        print("展示重點：pre_intent=out_of_domain，跳過 detect_intent 直達 out_of_domain 節點。")
        # ---------------------------------------------------------
        await run_test("今天天氣怎麼樣？", thread_id="demo_13", pre_intent="out_of_domain")


        # ---------------------------------------------------------
        print("\n\n📍 【劇本 14】無預判意圖 — 走原始 detect_intent 流程")
        print("展示重點：不帶 pre_intent，detect_intent 應正常呼叫 LLM 做分類。")
        # ---------------------------------------------------------
        # 對照組：不帶 pre_intent，路徑追蹤應顯示 detect_intent（非 pre-detected）
        await run_test("你好", thread_id="demo_14")
        """

    asyncio.run(main())