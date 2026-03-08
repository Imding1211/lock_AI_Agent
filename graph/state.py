import operator
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class GraphState(TypedDict):
    messages: Annotated[list, add_messages]   # Agent 對話歷史（LLM + Tool messages）
    question: str                             # 原始使用者輸入
    user_profile: str                         # 使用者輪廓
    answer: str                               # 最終回覆（給 app.py 讀取）
    history: Annotated[list, operator.add]      # 路徑追蹤（除錯用）
    chat_history: Annotated[list, operator.add] # 對話紀錄
