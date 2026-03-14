import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.builder import build_graph

async def test():
    print("Starting build_graph...")
    try:
        app = await build_graph()
        print("build_graph successful!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
