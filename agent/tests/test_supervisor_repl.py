"""
Level 2, interactive: run the real Supervisor graph — Enhancer's clarifying loop,
Researcher, Planner, HITL approval/edit/reject, and Booker's passenger-detail
collection through actual (test-mode) booking — and have an actual conversation
with it. Costs real API credit per turn. Run manually:

    PYTHONPATH=. python3 tests/test_supervisor_repl.py
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
        payload = result["__interrupt__"][0].value
        # Different steps interrupt with different payload shapes — Enhancer and
        # Booker ask a "question", HITL presents an "itinerary_summary" instead.
        prompt_text = payload.get("question") or payload.get("itinerary_summary")
        print(f"\nAssistant: {prompt_text}\n")
        reply = input("You: ")
        result = await graph.ainvoke(Command(resume=reply), config=config)

    print(f"\nAssistant: {result['messages'][-1].content}\n")


if __name__ == "__main__":
    asyncio.run(main())
