"""
Level 1, interactive: run the real Enhancer graph and have an actual back-and-forth
with it in the terminal. Costs a small amount of API credit per turn — run manually:

    PYTHONPATH=. python3 tests/test_enhancer_repl.py
"""

import asyncio
import uuid

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from enhancer.graph import build_enhancer_graph

load_dotenv()


async def main():
    graph = build_enhancer_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    opening = input("You: ")
    result = await graph.ainvoke({"messages": [HumanMessage(content=opening)]}, config=config)

    while "__interrupt__" in result:
        question = result["__interrupt__"][0].value["question"]
        print(f"\nEnhancer: {question}\n")
        reply = input("You: ")
        result = await graph.ainvoke(Command(resume=reply), config=config)

    print(f"\nEnhancer: {result['summary']}\n")
    print("--- Final structured request ---")
    print(result["request"])


if __name__ == "__main__":
    asyncio.run(main())
