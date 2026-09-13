"""
Level 2, interactive: run the real Supervisor graph — Enhancer's clarifying loop,
then Researcher, then the stub Planner — and have an actual conversation with it.
Costs API credit per turn (Enhancer's clarification loop + Researcher's search).
Run manually:

    python3 tests/test_supervisor_repl.py
"""

import asyncio
import uuid

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from supervisor.graph import build_supervisor_graph

load_dotenv()


async def main():
    graph = await build_supervisor_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    opening = input("You: ")
    result = await graph.ainvoke({"messages": [HumanMessage(content=opening)]}, config=config)

    while "__interrupt__" in result:
        question = result["__interrupt__"][0].value["question"]
        print(f"\nAssistant: {question}\n")
        reply = input("You: ")
        result = await graph.ainvoke(Command(resume=reply), config=config)

    print(f"\nAssistant: {result['messages'][-1].content}\n")


if __name__ == "__main__":
    asyncio.run(main())
