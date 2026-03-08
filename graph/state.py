import operator
from typing import Annotated, TypedDict

class GraphState(TypedDict):
    question: str
    standalone_query: str
    context: str
    answer: str
    intent: str
    slots: dict
    user_profile: str
    history: Annotated[list, operator.add]
    chat_history: Annotated[list, operator.add]
    previous_topic: str