import shutil
from langchain_core.documents import Document
from langchain_chroma import Chroma
from core.config import DB_CONFIG
from embeddings import get_embedding

def seed_databases():
    print(">>> 開始建立完美 Demo 測試假資料...\n")

    # 針對 db_smartlock_manual (產品手冊庫) 的假資料
    manual_docs = [
        Document(page_content="【通用教學：指紋設定步驟】\n1. 觸碰並喚醒密碼螢幕。\n2. 輸入「*#」與管理員密碼進入設定選單。\n3. 按下「1」選擇「新增使用者」，再選擇「新增指紋」。\n4. 將手指放在感應區，跟隨語音提示重複按壓 4 次，聽到「設定成功」即可完成。"),
        Document(page_content="【產品保固說明】\n所有電子鎖產品自購買日起享有兩年原廠保固，人為損壞與電池漏液不在此保固範圍內。")
    ]

    # 針對 db_troubleshooting (故障排除庫) 的假資料
    troubleshooting_docs = [
        Document(page_content="【故障排除：Philips Alpha 指紋設定失敗】\n若您的型號為 Philips Alpha 且指紋一直無法錄製或設定失敗：\n1. 請確認手指無汗水、油污或過於乾燥。\n2. 確認指紋感應區無嚴重刮痕。\n3. 系統可能產生暫存錯誤，請嘗試拔除內部電池重啟，或在管理員選單中刪除該組指紋後重新錄製。"),
        Document(page_content="【故障排除：密碼面板沒反應】\n若密碼面板亮起但觸控無反應，或完全不亮：\n1. 可能是電池沒電，請使用行動電源連接門鎖底部的 Type-C 緊急供電孔進行測試。\n2. 檢查面板表面是否有水滴或嚴重髒污干擾觸控。\n3. 若使用緊急供電仍無反應，且擦拭後無效，可能是主機板排線鬆脫，需安排原廠技師檢修。")
    ]

    for db in DB_CONFIG:
        if db.get("type") == "chroma":
            db_path = db.get("path", "./chroma_db_default")
            
            # 清除舊的資料庫檔案，確保資料乾淨
            try:
                shutil.rmtree(db_path)
                print(f"  [清理] 已刪除舊資料庫: {db_path}")
            except FileNotFoundError:
                pass
                
            print(f"  [寫入] 正在寫入資料至 {db['name']}...")
            embed_fn = get_embedding(db)
            vector_store = Chroma(persist_directory=db_path, embedding_function=embed_fn)

            if db["name"] == "db_smartlock_manual":
                vector_store.add_documents(manual_docs)
            elif db["name"] == "db_troubleshooting":
                vector_store.add_documents(troubleshooting_docs)

    print("\n>>> 假資料寫入完成！現在可以執行 python main.py 觀賞完美的 Demo 了。")

if __name__ == "__main__":
    seed_databases()