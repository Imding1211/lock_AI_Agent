# Smart Lock AI Agent

智慧電子鎖客服聊天機器人，基於 **LangGraph** 建構 RAG 檢索增強生成管線，透過 **LINE Bot** (FastAPI webhook) 對外服務。

## 功能特色

- **多 Agent 架構**：Router 意圖分類 → 專職 Agent 子圖（product_expert / troubleshooter / order_clerk / web_researcher）
- **多意圖平行派發**：Send() fan-out，一則訊息可同時觸發多個 Agent 並行處理
- **自主解決優先**：Agent 竭盡所能自主解決，僅在使用者明確堅持或涉及安全風險時轉接真人
- **對話記憶**：跨回合 chat_history + 話題偵測 session 遞增
- **使用者輪廓**：自動萃取並持久化使用者設備、地址、電話等個資
- **訊息防抖**：LINE 訊息緩衝合併，計時器重設機制避免碎片化處理
- **設定驅動**：透過 `config.toml` 管理所有設定，無需改程式碼即可擴充

## 系統架構

```
START → pre_process → router →  product_expert  ─┐
                            →  troubleshooter   ─┤
                            →  order_clerk       ─┤→ post_process → END
                            →  web_researcher   ─┤
                            →  out_of_domain     ─┤
                            →  transfer_human    ─┘
```

## 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數

複製 `.env.example`（或自行建立 `.env`），填入必要的金鑰：

```env
GEMINI_API_KEY="your-gemini-api-key"
VERTEX_PROJECT_ID="your-gcp-project-id"
VERTEX_LOCATION="us-central1"
LINE_CHANNEL_SECRET="your-line-channel-secret"
LINE_CHANNEL_ACCESS_TOKEN="your-line-channel-access-token"
```

### 3. 建立向量資料庫

```bash
python scripts/seed_db.py
```

### 4. 執行

```bash
# CLI 測試模式
python main.py

# LINE Bot webhook 伺服器
uvicorn app:app --reload
```

## 其他指令

```bash
# Mock 訂單 API（測試用）
uvicorn scripts.mock_api:app --port 8001

# 執行測試
python -m pytest tests/test_debounce.py
```

## LLM 供應商

透過 `config.toml` 的 `[llm].provider` 切換：

| Provider | 說明 | 驗證方式 |
| :--- | :--- | :--- |
| `ollama` | 本地 / 遠端 Ollama | 無需金鑰 |
| `gemini` | Google Gemini API | `GEMINI_API_KEY` |
| `vertexai` | Google Vertex AI | ADC (`gcloud auth application-default login`) |

## 專案結構

```
├── app.py                  # LINE Bot FastAPI webhook
├── main.py                 # CLI 測試入口
├── config.toml             # 系統設定檔
├── data/                   # 動態資料（db、profiles，gitignore）
├── scripts/                # 輔助腳本 (seed_db, mock_api)
├── docs/                   # 文件（reports / manuals / assets）
├── core/                   # 核心模組 (設定解析、防抖)
├── graph/                  # LangGraph 管線 (state, nodes, builder)
├── llms/                   # LLM 供應商 (ollama, gemini, vertexai)
├── embeddings/             # Embedding 供應商
├── retrievers/             # 檢索器 (chroma, api, web_search)
├── memory/                 # 對話記憶 checkpointer
├── profiles/               # 使用者輪廓管理
└── tests/                  # 測試
```
