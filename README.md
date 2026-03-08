# Smart Lock AI Agent

智慧電子鎖客服聊天機器人，基於 **LangGraph** 建構 RAG 檢索增強生成管線，透過 **LINE Bot** (FastAPI webhook) 對外服務。

## 功能特色

- **多源檢索降級鏈**：產品手冊 → 故障排除 → 訂單 API → 網頁搜尋 → 轉接真人
- **意圖路由**：自動偵測使用者意圖，導向對應的檢索節點
- **Slot Filling**：缺少必要資訊（品牌、型號）時主動反問
- **對話記憶**：跨回合記憶與指代還原 (Query Rewrite)
- **使用者輪廓**：自動記錄並載入使用者偏好與設備資訊
- **智慧防抖**：LINE 訊息緩衝合併，避免碎片化處理
- **設定驅動**：透過 `config.toml` 管理所有設定，無需改程式碼即可擴充

## 系統架構

```
START → load_user_profile → rewrite_query → detect_intent → extract_slots
  → ask_missing_slots → [retriever node] → grader → generate → update_user_profile → END
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
python seed_db.py
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
# 單獨建立向量資料庫
python build_default_db.py        # → ./chroma_db_default
python build_troubleshoot_db.py   # → ./chroma_db_troubleshoot

# Mock 訂單 API（測試用）
uvicorn mock_api:app --port 8001

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
├── seed_db.py              # 向量資料庫初始化
├── mock_api.py             # Mock 訂單 API
├── core/                   # 核心模組 (設定解析、防抖)
├── graph/                  # LangGraph 管線 (state, nodes, builder)
├── llms/                   # LLM 供應商 (ollama, gemini, vertexai)
├── embeddings/             # Embedding 供應商
├── retrievers/             # 檢索器 (chroma, api, web_search)
├── memory/                 # 對話記憶 checkpointer
├── profiles/               # 使用者輪廓管理
├── tests/                  # 測試
└── docs/                   # 開發文件與架構圖
```
