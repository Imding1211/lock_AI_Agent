# 系統設定檔 (`config.toml`) 說明文件

本文件詳細說明 RAG 客服系統的核心設定檔 `config.toml` 中各項區塊與參數的意義。

## 1. 系統全局設定 `[system]`

定義系統的業務守備範圍（Domain Guardrail）。這會作為「評分員（Grader）」的嚴格護欄，防止模型回答與業務無關的問題（例如被誘導去回答天氣、新聞或無關的閒聊）。

```toml
[system]
domain = "電子鎖、智慧門鎖相關的產品、安裝、故障排除與售後服務"

```

* **domain**: 一段清晰描述業務範圍的字串。系統在檢索與生成回覆時，會嚴格把關問題與參考資料是否符合此領域。

## 2. 核心語言模型設定 `[llm]`

設定系統大腦（主要負責意圖判斷、資訊盤點、改寫問題與最終生成）。透過 LLM Factory 動態載入。

```toml
[llm]
provider = "ollama"           # 可選: "ollama", "gemini" 等 (需在 llms/ 註冊)
model_name = "gemma3:4b"      # 模型名稱
temperature = 0.7             # 創造力指數 (0.0 ~ 1.0，建議客服情境設低一點)
base_url = "http://localhost:11434" # Ollama 專用連線網址
# api_key_env = "GEMINI_API_KEY"    # 若使用 Gemini 等雲端服務，指定環境變數名稱

```

## 3. 對話記憶儲存機制 `[memory]`

管理系統如何記住跨回合的歷史對話（Checkpointer）。透過 Memory Factory 動態載入。

```toml
[memory]
type = "memory"  # 可選: "memory" (暫存), "sqlite" (本地持久化), "postgres" (資料庫持久化)
# path = "./chat_history.db"  # 當 type 為 sqlite 時，指定資料庫檔案路徑

```

## 4. 必填資訊收集 (槽位填充) `[required_slots]`

定義系統在進行資料庫檢索前，必須向使用者釐清的關鍵資訊。若使用者未提供，系統會自動中斷檢索並生成「親切的反問句」。若使用者明確表示「不知道」，系統會記錄為 `UNKNOWN` 並繼續流程，並在最終回覆時主動詢問是否轉接真人。

```toml
[required_slots]
device_brand = "使用者的電子鎖品牌（例如：Philips 等等）。"
device_model = "使用者的電子鎖型號（例如：X1 Pro, A3 等等）。"

```

* **參數名稱 (Key)**: 程式內部使用的變數名稱（如 `device_model`）。
* **參數值 (Value)**: 給 LLM 看的欄位定義與提示，寫得越清楚，LLM 抽取的準確率越高。

## 5. 意圖偵測與分流路由 `[[intents]]`

定義系統的「語意路由（Semantic Routing）」。系統總機會根據使用者的問題，將流程直接「空降」到對應的目標節點，大幅節省不必要的檢索時間。

```toml
[[intents]]
name = "order_status"
description = "使用者想查詢訂單進度、出貨狀況、物流狀態或維修進度"
target = "db_order_api"  # 必須對應到 [[databases]] 裡面的 name，或是 "human"

[[intents]]
name = "troubleshooting"
description = "使用者遇到設備故障、沒有反應、錯誤代碼或需要排除問題"
target = "db_troubleshooting"

[[intents]]
name = "transfer_human"
description = "使用者明確要求轉接真人客服，或是對『是否轉接真人』的問題回答『好』、『需要』。"
target = "human" # 直接觸發轉接真人節點

[[intents]]
name = "general_knowledge"
description = "關於產品規格、如何設定、一般操作問題，或是其他無法分類的問題"
target = "db_smartlock_manual" # 通常作為預設入口 (Fallback)

```

## 6. 知識庫與檢索器設定 `[[databases]]`

系統的資料來源。採用陣列設計，系統會依據此處定義的順序形成「階梯式降級（Fallback Chain）」。當上一個資料庫查無資料時，會自動往下一個資料庫查詢。支援透過工廠模式掛載不同類型的檢索器。

### A. 向量資料庫 (ChromaDB)

結合 Embeddings Factory，將文字轉為向量進行語意搜尋。

```toml
[[databases]]
name = "db_smartlock_manual"      # 節點名稱 (需唯一，供 intents 的 target 綁定)
type = "chroma"                   # 檢索器類型
path = "./chroma_db_manual"       # 資料庫本機路徑
top_k = 2                         # 每次檢索取回最相關的幾筆資料
embedding_provider = "ollama"     # Embedding 模型供應商
embedding_model = "nomic-embed-text" # Embedding 模型名稱
embedding_base_url = "http://localhost:11434"

```

### B. 內部 API 串接 (API Store)

適合用來查詢即時的動態資料（如訂單狀態、庫存）。

```toml
[[databases]]
name = "db_order_api"
type = "api"
endpoint = "https://api.example.com/orders" # API 端點
method = "GET"                    # HTTP 方法 (GET/POST)
query_param = "order_id"          # 傳遞查詢字串的參數名稱
response_key = "data"             # JSON 回傳格式中，欲萃取的資料欄位
timeout = 5                       # 連線超時設定 (秒)

```

### C. 外部網頁搜尋 (Web Search)

作為最後的知識防線，遇到內部資料庫與 API 都查不到的問題時，啟動外部搜尋引擎。

```toml
[[databases]]
name = "db_web_search"
type = "web_search"
search_engine = "duckduckgo"      # 搜尋引擎供應商
max_results = 3                   # 最多參考幾篇網頁結果

```

