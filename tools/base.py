from abc import ABC, abstractmethod
from typing import Any, Dict
from langchain_core.tools import StructuredTool


class BaseTool(ABC):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.setup()

    @abstractmethod
    def setup(self):
        pass

    @abstractmethod
    def as_langchain_tool(self) -> StructuredTool:
        pass
