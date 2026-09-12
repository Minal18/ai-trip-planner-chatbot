from datetime import date
from typing import Annotated, Optional, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from enhancer.nodes import AskQuestion, RequestReady, parse_response
from enhancer.prompts import build_system_prompt


class EnhancerState(TypedDict):
    messages: Annotated[list, add_messages]
    complete: bool
    pending_question: Optional[str]
    request: Optional[dict]
    summary: Optional[str]


def build_enhancer_graph():
    model = ChatAnthropic(model="claude-sonnet-5").bind_tools(
        [AskQuestion, RequestReady], tool_choice="any"
    )

    async def ask_or_complete(state: EnhancerState) -> dict:
        system_prompt = build_system_prompt(today=date.today().isoformat())
        response = await model.ainvoke([SystemMessage(content=system_prompt)] + state["messages"])
        parsed = parse_response(response)
        # Anthropic requires every tool_use block to be followed by a tool_result —
        # these two tools are structured-output-only and never actually execute, so
        # we still owe the API a synthetic acknowledgment before the next turn.
        tool_ack = ToolMessage(content="Acknowledged.", tool_call_id=response.tool_calls[0]["id"])
        return {**parsed, "messages": [response, tool_ack]}

    def wait_for_traveler(state: EnhancerState) -> dict:
        reply = interrupt({"question": state["pending_question"]})
        return {"messages": [HumanMessage(content=reply)]}

    def route(state: EnhancerState) -> str:
        return END if state["complete"] else "wait_for_traveler"

    graph = StateGraph(EnhancerState)
    graph.add_node("ask_or_complete", ask_or_complete)
    graph.add_node("wait_for_traveler", wait_for_traveler)

    graph.add_edge(START, "ask_or_complete")
    graph.add_conditional_edges("ask_or_complete", route, {END: END, "wait_for_traveler": "wait_for_traveler"})
    graph.add_edge("wait_for_traveler", "ask_or_complete")

    return graph.compile(checkpointer=MemorySaver())
