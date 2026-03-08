import os
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

load_dotenv()

raw_documents = [
    Document(
        page_content="【智能門鎖指紋設定方式】喚醒門鎖螢幕後，輸入「*#管理員密碼#」進入系統設定選單。按下「1」選擇新增使用者，接著依照語音提示，將手指放在指紋感應區按壓 4 次，聽到「設定成功」即可。", 
        metadata={"source": "user_manual.txt"}
    ),
    Document(
        page_content="【電池更換教學】當門鎖語音提示「電量過低」時，請開啟內側電池蓋，更換 4 顆 3 號 (AA) 鹼性電池。", 
        metadata={"source": "user_manual.txt"}
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

db_path = "./chroma_db_default" 

print(f"開始將 {len(splits)} 個文本區塊寫入新的 ChromaDB ({db_path})...")
vector_store = Chroma.from_documents(
    documents=splits,
    embedding=embeddings,
    persist_directory=db_path
)

print("知識庫建立完成！")