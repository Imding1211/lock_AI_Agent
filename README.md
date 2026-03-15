# Smart Lock AI Agent

智慧電子鎖客服聊天機器人，基於 LangGraph 建構 RAG 檢索增強生成管線，透過 LINE Bot (FastAPI webhook) 對外服務。

## 功能特色

- 零硬編碼設定驅動：所有行為參數、Prompt 路徑、Regex 均由 config.toml 控制，13 個區塊涵蓋系統全貌，無需更動程式碼即可擴充。
- 雙軌持久化日誌：chat_history.db（對話記憶與語意摘要）與 audit_log.db（原始日誌審計）獨立運作，確保對話延續性與審計完整性。
- 核心引擎分離：推理引擎 (LLM) 與語意引擎 (Embedding) 獨立配置，各向量資料庫獨立設定 Embedding 參數。
- 插件式工具架構：tools/ 目錄採二層繼承體系，落實「一工具一檔案」規範，支援檢索類與行為類工具快速擴充。
- 多 Agent 平行協作：Router 意圖分類搭配 Send() fan-out 機制，支援單一訊息多意圖平行處理與自動回覆合併。
- 智能使用者輪廓：自動萃取並持久化使用者設備、地址與電話，並在轉接真人時自動預填表單。
- 平台適配優化：針對 LINE 環境實作訊息防抖 (Debounce) 合併、Loading 動畫，以及自動 Markdown 格式清洗。

## 系統架構

```
START → pre_process → manage_memory → router →  product_expert  ─┐
                                             →  troubleshooter   ─┤
                                             →  order_clerk       ─┤→ merge_answers → update_profile → post_process → END
                                             →  web_researcher   ─┤
                                             →  out_of_domain     ─┤
                                             →  transfer_human    ─┘
```

## 快速開始

### 1. 安裝依賴環境

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數

複製 .env.example 並建立 .env 檔案，填入以下必要金鑰：

```env
# LINE Bot 認證
LINE_CHANNEL_SECRET="your-line-channel-secret"
LINE_CHANNEL_ACCESS_TOKEN="your-line-channel-access-token"

# LLM 供應商金鑰 (依據 config.toml 設定)
GEMINI_API_KEY="your-gemini-api-key"        # provider=gemini
VERTEX_PROJECT_ID="your-gcp-project-id"     # provider=vertexai
VERTEX_LOCATION="us-central1"               # provider=vertexai
OLLAMA_BASE_URL="http://localhost:11434"    # provider=ollama (選填)

# 外部資料源與持久化 (選填)
ORDER_API_URL="https://api.example.com/v1/status"
POSTGRES_URI="postgresql://user:pass@host:5432/dbname"
```

### 3. 初始化向量資料庫

```bash
python scripts/seed_db.py
```

### 4. 啟動服務

```bash
# LINE Bot Webhook 伺服器
uvicorn app:app --reload

# CLI 測試模式 (免 LINE 串接)
python main.py
```

## 運維與開發工具

```bash
# 查看審計日誌 (含 RAW/USER/AI 角色標記)
python scripts/view_logs.py

# 啟動測試用 Mock 訂單 API
uvicorn scripts.mock_api:app --port 8001

# 執行自動化測試
python -m pytest tests/
```

## 專案結構

```
lock_AI_Agent/
├── app.py                  # LINE Bot Webhook 入口與防抖層
├── main.py                 # CLI 測試與 Demo 腳本
├── config.toml             # 全系統核心設定檔 (13 個區塊)
├── core/                   # 核心配置與常數載入
├── graph/                  # LangGraph 節點邏輯與圖表建構
├── agents/                 # 多 Agent Prompt 模板與子圖產生器
├── tools/                  # 工具箱 (BaseTool 二層架構，一檔案一工具)
│   ├── base.py             # 基礎類別與 LangChain 工具轉換邏輯
│   ├── base_retriever.py   # 檢索類工具通用介面
│   └── transfer_human.py   # 轉接真人業務邏輯工具
├── llms/                   # LLM 引擎工廠 (Ollama/Gemini/Vertex AI)
├── embeddings/             # Embedding 引擎工廠（Per-DB 配置）
├── storage/                # 審計日誌持久化模組
├── memory/                 # 對話記憶 Checkpointer 模組
├── profiles/               # 使用者輪廓管理模組
├── scripts/                # 輔助腳本 (資料初始化、日誌檢視)
├── data/                   # 持久化資料目錄
│   ├── db/                 # SQLite 資料庫（向量資料存於 pgvector）
│   └── profiles/           # 使用者輪廓 Markdown 檔案
└── docs/                   # 技術文件體系 (手冊、進度報告、架構圖)
```
