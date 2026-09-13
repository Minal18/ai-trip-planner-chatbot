"""
Level 1/2, live (real API calls, real cost) — but scripted and assertion-based,
unlike test_supervisor_repl.py. Specifically verifies the riskiest mechanic in the
whole build: that Enhancer's interrupt() correctly propagates up through Supervisor
to the top level, AND that resuming continues Enhancer's own internal clarification
loop rather than silently restarting it from scratch.

Run manually:

    PYTHONPATH=. python3 tests/test_supervisor_interrupt_propagation.py
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
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    # Deliberately underspecified — must take at least two clarifying turns.
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="I want to fly to Austin")]}, config=config
    )

    assert "__interrupt__" in result, (
        "Expected Enhancer's interrupt() to propagate up through Supervisor and "
        "surface in the top-level result — it didn't. Nested checkpointing may be "
        "broken (e.g. Enhancer given its own checkpointer again instead of "
        "inheriting Supervisor's)."
    )
    question_1 = result["__interrupt__"][0].value["question"]
    print(f"Q1: {question_1}")

    result = await graph.ainvoke(Command(resume="From Seattle"), config=config)

    assert "__interrupt__" in result, (
        "Expected a second clarifying question (still missing dates/travelers) — "
        "got none. Enhancer may have incorrectly declared 'complete' after only "
        "one answer."
    )
    question_2 = result["__interrupt__"][0].value["question"]
    print(f"Q2: {question_2}")

    assert question_2 != question_1, (
        "Second question is identical to the first — this is the specific failure "
        "mode we're guarding against: Enhancer's internal loop restarting from "
        "scratch on every Supervisor-level resume, instead of continuing from "
        "where it paused."
    )

    # Finish the conversation, then check the FINAL structured output — a more
    # reliable signal than guessing intent from question wording. If Enhancer had
    # silently lost turn 1's answer, origin would come back wrong or missing here.
    result = await graph.ainvoke(Command(resume="November 15th, one-way, 1 adult"), config=config)
    while "__interrupt__" in result:
        result = await graph.ainvoke(Command(resume="that's correct, proceed"), config=config)

    assert result["request"]["origin"] == "SEA", (
        f"Expected origin SEA (from turn 1's 'Seattle' answer) to survive into the "
        f"final request, got: {result['request'].get('origin')!r}. Enhancer likely "
        f"lost earlier conversation state across a resume."
    )

    print("\nPASSED: interrupt propagated to top level, resume continued Enhancer's "
          "loop instead of restarting it, and turn 1's answer survived to the final "
          f"structured request: {result['request']}")


if __name__ == "__main__":
    asyncio.run(main())
