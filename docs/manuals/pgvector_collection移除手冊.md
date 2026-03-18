# pgvector Collection 移除手冊

本文件說明如何從系統中完整移除一個 pgvector collection（以 `smartlock_manual` 和 `troubleshooting` 為例）。

---

## 1. 清除 PostgreSQL 資料

所有 collection 的向量資料共用 `langchain_pg_embedding` 表，collection 索引存於 `langchain_pg_collection` 表。需依序刪除：

```sql
-- Step 1：刪除向量資料
DELETE FROM langchain_pg_embedding
WHERE collection_id IN (
    SELECT uuid FROM langchain_pg_collection
    WHERE name IN ('smartlock_manual', 'troubleshooting')
);

-- Step 2：刪除 collection 索引
DELETE FROM langchain_pg_collection
WHERE name IN ('smartlock_manual', 'troubleshooting');
```

> 順序不可反轉——`langchain_pg_embedding.collection_id` 是指向 `langchain_pg_collection.uuid` 的 FK。

## 2. 移除 config.toml 設定

### 2.1 移除 `[[databases]]` 區塊

刪除以下兩個區塊：

```toml
# 刪除此區塊
[[databases]]
name               = "db_smartlock_manual"
type               = "pgvector"
...

# 刪除此區塊
[[databases]]
name               = "db_troubleshooting"
type               = "pgvector"
...
```

### 2.2 移除 Agent tools 引用

從對應 Agent 的 `tools` 陣列中移除已刪除的資料庫名稱：

```toml
# 修改前
[[agents]]
name  = "product_expert"
tools = ["db_smartlock_manual", "transfer_to_human"]

# 修改後
[[agents]]
name  = "product_expert"
tools = ["transfer_to_human"]
```

```toml
# 修改前
[[agents]]
name  = "troubleshooter"
tools = ["db_troubleshooting", "transfer_to_human"]

# 修改後
[[agents]]
name  = "troubleshooter"
tools = ["transfer_to_human"]
```

## 3. 移除 Seed 腳本資料

`scripts/seed_db.py` 中刪除對應的 Document 清單與寫入邏輯：

- `manual_docs` 清單（對應 `smartlock_manual`）
- `troubleshooting_docs` 清單（對應 `troubleshooting`）
- `seed_databases()` 中根據 `db["name"]` 分派寫入的 `if/elif` 分支

## 4. 驗證

1. 連線 PostgreSQL 確認資料已清除：
   ```sql
   SELECT name FROM langchain_pg_collection;
   ```
2. 啟動系統 `python main.py`，確認啟動日誌不再出現已移除的工具名稱
