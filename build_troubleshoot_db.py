import os
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

load_dotenv()

raw_documents = [
    Document(
        page_content="【突發狀況：門鎖完全沒電被關在門外】如果智慧門鎖完全耗盡電量導致無法操作，請勿驚慌。您可以使用行動電源（Power Bank）接上 Type-C 傳輸線，插入門鎖外側底部的緊急供電孔進行臨時供電，喚醒門鎖後輸入密碼即可開門。或是使用隨附的實體備用鑰匙直接開鎖。", 
        metadata={"source": "troubleshoot_guide.txt", "category": "power"}
    ),
    Document(
        page_content="【故障排除：指紋一直無法辨識】如果遇到指紋辨識失敗率過高的問題，請先使用乾淨的微濕布擦拭指紋感應區，避免油污或灰塵干擾。若使用者的手指有脫皮或過於乾燥的情況，建議在系統中為同一根手指多錄製幾組不同角度的指紋，或改用密碼解鎖。", 
        metadata={"source": "troubleshoot_guide.txt", "category": "sensor"}
    ),
    Document(
        page_content="【故障排除：觸控鍵盤亮起但無法按壓】若喚醒螢幕後，密碼鍵盤的數字亮起但觸控毫無反應，可能是系統當機。請打開室內側的電池蓋，長按紅色的「Reset 重置鍵」5 秒鐘，系統將會重新啟動。重新啟動不會刪除您原本設定的指紋與密碼。", 
        metadata={"source": "troubleshoot_guide.txt", "category": "system"}
    )
]

print("正在載入 Ollama Embedding 模型...")
base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
embeddings = OllamaEmbeddings(
    model="nomic-embed-text",
    base_url=base_url
)

print("正在切割文件區塊...")
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=200,
    chunk_overlap=30
)
splits = text_splitter.split_documents(raw_documents)

db_path = "./chroma_db_troubleshoot" 

print(f"開始將 {len(splits)} 個文本區塊寫入新的 ChromaDB ({db_path})...")
vector_store = Chroma.from_documents(
    documents=splits,
    embedding=embeddings,
    persist_directory=db_path
)

print("知識庫建立完成！")