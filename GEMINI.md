# GEMINI.md - lock_AI 專案指令手冊

本文件為 Gemini CLI 提供專案背景、開發規範及操作指令。

## 專案概述
`lock_AI` 是一個智慧門鎖（電子鎖）客服機器人，主要服務於產品安裝、故障排除與售後服務。
- **核心技術**：Python 3.10+, LangGraph, LangChain, FastAPI, ChromaDB (Vector DB), Line Bot SDK.
- **LLM 支援**：Ollama (本地) 或 Google Gemini (雲端)。
- **架構設計**：
  - 使用 **LangGraph** 構建對話狀態機。
  - **RAG 降級鏈**：產品手冊 (Chroma) -> 故障排除 (Chroma) -> 訂單 API -> 網頁搜尋 (DuckDuckGo) -> 真人客服。
  - **配置驅動**：系統行為（如 LLM 選擇、檢索器優先級、意圖路由）皆由 `config.toml` 控制。
  - **擴充性**：採用工廠模式 (Factory Pattern) 與註冊表 (Registry) 機制。

## 核心指令

### 1. 環境準備
```bash
# 安裝依賴
pip install -r requirements.txt
```

### 2. 資料庫建置與初始化
```bash
# 初始化 Demo 資料（清除並重建所有向量庫）
python seed_db.py

# 單獨建置產品手冊向量庫
python build_default_db.py

# 單獨建置故障排除向量庫
python build_troubleshoot_db.py
```

### 3. 執行與測試
```bash
# 啟動 LINE Bot Webhook 伺服器 (正式/開發入口)
uvicorn app:app --reload

# 啟動 CLI 測試介面 (模擬對話，無需 LINE Bot)
python main.py

# 啟動 Mock Order API (用於測試訂單查詢功能)
uvicorn mock_api:app --port 8001
```

## 開發規範與慣例

### 語言與文字
- **使用者介面**：所有回覆、系統通知及對話內容一律使用 **繁體中文 (zh-TW)**。
- **程式碼與註解**：變數命名使用英文，關鍵邏輯建議附帶繁體中文註解。
- **LLM Prompt**：系統提示詞 (System Prompt) 主要使用英文以確保模型表現，但最終輸出須為繁體中文。

### 架構與擴充
- **LangGraph 節點**：所有節點函數（位於 `graph/nodes.py`）必須為 `async`，且回傳值應為字典以更新 `GraphState`。
- **配置變更**：優先修改 `config.toml` 而非硬編碼 (Hardcode)。敏感資訊（API Key）請放在 `.env`。
- **註冊新元件**：
  - **檢索器**：於 `retrievers/` 建立新檔案並在 `retrievers/__init__.py` 的 `REGISTRY` 註冊。
  - **模型**：於 `llms/` 或 `embeddings/` 建立並在對應的 `__init__.py` 註冊。

### 測試
- 測試案例位於 `tests/`，使用 `pytest` 執行。
- 修改對話流程後，應使用 `python main.py` 驗證不同意圖的路由是否正確。

## 關鍵檔案索引
- `config.toml`: 系統全局設定（大腦核心）。
- `app.py`: LINE Bot Webhook 與訊息防抖 (Debounce) 邏輯。
- `graph/builder.py`: LangGraph 對話流程定義。
- `graph/nodes.py`: 各個對話節點的具體 LLM 邏輯。
- `core/config.py`: 設定檔解析器。
