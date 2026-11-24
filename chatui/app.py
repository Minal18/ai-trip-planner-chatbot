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

# python-dotenv's default load_dotenv() only searches upward from the current
# working directory — since chatui/ is a sibling of agent/, not a parent, it
# would never find agent/.env. Point at it explicitly (same reasoning as the
# sys.path.insert above: this app borrows agent/'s whole environment).
load_dotenv(Path(__file__).resolve().parent.parent / "agent" / ".env")

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


# Shown while each step runs, so the traveler sees progress instead of silence
# during a multi-second turn (search + plan is ~10s+ of LLM and API calls).
# Keyed by graph node name — top-level Supervisor nodes plus a few inner subgraph
# nodes, since stream subgraphs=True reports both. Unlisted nodes (deterministic
# and near-instant) keep whatever status is already showing.
STEP_LABELS = {
    "enhancer": "Understanding your trip…",
    "planner": "Building your itinerary…",
    "human_review": "Reading your reply…",
    "classify_edit_feedback": "Working out what to change…",
    "offer_retry": "Reading your reply…",
    "collect_passenger_details": "Reading traveler details…",
    "resolve_stay_rate": "Checking the hotel rate…",
    "book": "Booking…",
}
DOMAIN_NAMES = {"flights": "flights", "stays": "hotels", "cars": "rental cars"}


def _step_label(name: str, task_input) -> str | None:
    if name == "researcher":
        request = (task_input or {}).get("request") or {}
        domains = [DOMAIN_NAMES.get(d, d) for d in request.get("domains") or []]
        if not domains:
            return "Searching for options…"
        joined = domains[0] if len(domains) == 1 else ", ".join(domains[:-1]) + " and " + domains[-1]
        return f"Searching {joined}…"
    return STEP_LABELS.get(name)


@cl.on_message
async def on_message(message: cl.Message):
    graph = await _get_graph()
    thread_id = cl.user_session.get("thread_id")
    config = {"configurable": {"thread_id": thread_id}}
    awaiting_interrupt = cl.user_session.get("awaiting_interrupt")

    if awaiting_interrupt:
        graph_input = Command(resume=message.content)
    else:
        graph_input = {"messages": [HumanMessage(content=message.content)]}

    # One status message, edited in place as steps start, then removed once the
    # real reply is ready.
    status = None
    try:
        # stream_mode="tasks" emits an event when each node starts (with its
        # input) and finishes; only the start events are used here.
        async for _namespace, event in graph.astream(
            graph_input, config=config, stream_mode="tasks", subgraphs=True
        ):
            if "input" not in event:
                continue  # a "finished" event
            label = _step_label(event["name"], event["input"])
            if not label:
                continue
            if status is None:
                status = cl.Message(content=f"⏳ {label}")
                await status.send()
            elif status.content != f"⏳ {label}":
                status.content = f"⏳ {label}"
                await status.update()
        snapshot = await graph.aget_state(config)
    except Exception as e:
        # A real UI boundary — an unhandled error here shouldn't crash the chat
        # session, just surface what happened and let the traveler try again.
        if status is not None:
            await status.remove()
        cl.user_session.set("awaiting_interrupt", False)
        await cl.Message(content=f"Something went wrong: {e}\n\nYou can try again.").send()
        return

    if status is not None:
        await status.remove()

    if snapshot.interrupts:
        payload = snapshot.interrupts[0].value
        # Different steps interrupt with different payload shapes — Enhancer and
        # Booker ask a "question", HITL presents an "itinerary_summary" instead.
        prompt_text = payload.get("question") or payload.get("itinerary_summary")
        cl.user_session.set("awaiting_interrupt", True)
        await cl.Message(content=prompt_text).send()
    else:
        cl.user_session.set("awaiting_interrupt", False)
        await cl.Message(content=snapshot.values["messages"][-1].content).send()
