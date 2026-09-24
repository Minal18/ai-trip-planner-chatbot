"""
Chainlit chat UI for the AI Trip Planner — a real presentation layer over
build_supervisor_graph(), replacing the terminal REPL for interactive testing.

Run from this directory (with agent/.venv activated):

    chainlit run app.py -w
"""

import sys
import uuid
from pathlib import Path

# This is a thin presentation layer directly over agent/'s compiled graph — reuse
# agent/.venv rather than duplicating its dependencies in a second venv.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import chainlit as cl
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from supervisor.graph import build_supervisor_graph

load_dotenv()

_graph = None  # built once, lazily; the compiled graph itself is stateless and
# safe to share across chat sessions — only thread_id (per-session) makes each
# conversation distinct.


async def _get_graph():
    global _graph
    if _graph is None:
        _graph = await build_supervisor_graph()
    return _graph


@cl.on_chat_start
async def on_chat_start():
    await _get_graph()
    cl.user_session.set("thread_id", str(uuid.uuid4()))
    cl.user_session.set("awaiting_interrupt", False)
    await cl.Message(
        content="Hi! Tell me about the trip you'd like to plan — where you're headed, "
        "when, and what you need (flight, hotel, rental car)."
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    graph = await _get_graph()
    thread_id = cl.user_session.get("thread_id")
    config = {"configurable": {"thread_id": thread_id}}
    awaiting_interrupt = cl.user_session.get("awaiting_interrupt")

    try:
        if awaiting_interrupt:
            result = await graph.ainvoke(Command(resume=message.content), config=config)
        else:
            result = await graph.ainvoke({"messages": [HumanMessage(content=message.content)]}, config=config)
    except Exception as e:
        # A real UI boundary — an unhandled error here shouldn't crash the chat
        # session, just surface what happened and let the traveler try again.
        cl.user_session.set("awaiting_interrupt", False)
        await cl.Message(content=f"Something went wrong: {e}\n\nYou can try again.").send()
        return

    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        # Different steps interrupt with different payload shapes — Enhancer and
        # Booker ask a "question", HITL presents an "itinerary_summary" instead.
        prompt_text = payload.get("question") or payload.get("itinerary_summary")
        cl.user_session.set("awaiting_interrupt", True)
        await cl.Message(content=prompt_text).send()
    else:
        cl.user_session.set("awaiting_interrupt", False)
        await cl.Message(content=result["messages"][-1].content).send()
