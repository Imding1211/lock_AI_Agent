# 20260313 — 全域 Embedding 引擎與配置驅動

## 目標

將分散在各 `[[databases]]` 條目中的 Embedding 設定提升為全域引擎，與 LLM 同等地位，消除 DRY 違反問題。

## 異動摘要

### 程式碼

| 檔案 | 動作 | 說明 |
|------|------|------|
| `config.toml` | 修改 | 新增 `[embedding]` 區塊（§6），移除兩個 Chroma `[[databases]]` 中重複的 `embedding_*` 欄位，區塊編號由 13 → 14 |
| `core/config.py` | 修改 | `load_config()` 新增讀取 `embedding` 區塊，匯出 `EMBEDDING_CONFIG` 全域變數 |
| `embeddings/__init__.py` | 修改 | `get_embedding()` 新增 fallback 邏輯：未帶 `embedding_provider` 時自動使用全域 `EMBEDDING_CONFIG`，並做 key 正規化 |

### 無需修改

| 檔案 | 原因 |
|------|------|
| `retrievers/chroma_store.py` | `get_embedding(self.config)` 呼叫不變，移除 `embedding_provider` 後自動 fallback |
| `embeddings/ollama_embed.py` | key 正規化在 `get_embedding()` 處理，builder 函數不需修改 |

### 文件

| 檔案 | 說明 |
|------|------|
| `docs/assets/architecture.mmd` | 新增 `EMBEDDING_ENGINE` 節點與至 Chroma DB 的連線 |
| `docs/manuals/系統架構與流程圖.md` | Support_Layer 新增 Embedding Factory 節點 |
| `docs/manuals/系統擴充開發指南.md` | 架構總覽新增 `[embedding]` 路徑，§5 更新為全域設定方式 |
| `docs/manuals/系統設定檔 (config.toml) 說明文件.md` | 新增 §6 `[embedding]` 區塊說明，ChromaDB 範例移除重複欄位 |

## 技術設計

### Fallback 機制

```python
def get_embedding(config: dict = None):
    if not config or not config.get("embedding_provider"):
        # fallback 至全域 EMBEDDING_CONFIG
        cfg = {
            "embedding_provider": EMBEDDING_CONFIG.get("provider"),
            "embedding_model": EMBEDDING_CONFIG.get("model"),
            ...
        }
    else:
        cfg = config  # 保留 per-database override 能力
```

### 向後相容

- 若個別 `[[databases]]` 仍帶有 `embedding_provider` 欄位，會優先使用（per-database override）
- 全域設定僅在 config 中不含 `embedding_provider` 時生效

## 驗證項目

- [x] `config.toml` 的 Chroma 條目已無 `embedding_*` 欄位
- [x] `EMBEDDING_CONFIG` 正確載入全域設定
- [x] 架構圖中 `EMBEDDING_ENGINE` 節點正確顯示
