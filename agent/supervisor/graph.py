from typing import Annotated, Optional, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from enhancer.graph import build_enhancer_graph
from hitl.nodes import Approve, RequestEdits, Reject, parse_response as parse_hitl_response
from hitl.prompts import SYSTEM_PROMPT as HITL_SYSTEM_PROMPT
from planner.graph import build_planner_graph
from researcher.graph import build_researcher_graph
from supervisor.nodes import decide_next_step


class SupervisorState(TypedDict):
    messages: Annotated[list, add_messages]
    request: Optional[dict]
    summary: Optional[str]
    research_results: Optional[dict]
    insufficient_domains: Optional[list]
    itinerary: Optional[dict]
    itinerary_status: Optional[str]
    edit_feedback: Optional[str]


async def build_supervisor_graph():
    enhancer_graph = build_enhancer_graph(use_own_checkpointer=False)
    researcher_graph = await build_researcher_graph()
    planner_graph = build_planner_graph()
    hitl_model = ChatAnthropic(model="claude-sonnet-5").bind_tools([Approve, RequestEdits, Reject], tool_choice="any")

    async def run_enhancer(state: SupervisorState) -> dict:
        result = await enhancer_graph.ainvoke({"messages": state["messages"]})
        return {"request": result["request"], "summary": result["summary"]}

    async def run_researcher(state: SupervisorState) -> dict:
        result = await researcher_graph.ainvoke({"request": state["request"]})
        return {
            "research_results": result["research_results"],
            "insufficient_domains": result["insufficient_domains"],
        }

    async def run_planner(state: SupervisorState) -> dict:
        result = await planner_graph.ainvoke(
            {
                "request": state["request"],
                "research_results": state["research_results"],
                "edit_feedback": state.get("edit_feedback"),
            }
        )
        return {"itinerary": result["itinerary"]}

    async def run_human_review(state: SupervisorState) -> dict:
        reply = interrupt({"itinerary_summary": state["itinerary"]["summary"]})
        response = await hitl_model.ainvoke([SystemMessage(content=HITL_SYSTEM_PROMPT), HumanMessage(content=reply)])
        result = parse_hitl_response(response)
        return {**result, "messages": [HumanMessage(content=reply)]}

    def announce_outcome(state: SupervisorState) -> dict:
        status = state["itinerary_status"]
        if status == "approved":
            # Placeholder until Booker exists — no booking happens yet.
            text = "Great — approved. (Booking isn't wired up yet, so nothing has actually been booked.)"
        elif status == "rejected":
            text = "No problem — let me know if you'd like to start planning a different trip."
        else:  # edit_requested — temporary placeholder, replaced once edit classification is built
            text = f"Got your feedback ({state['edit_feedback']!r}) — edit handling isn't wired up yet."
        return {"messages": [AIMessage(content=text)]}

    graph = StateGraph(SupervisorState)
    graph.add_node("enhancer", run_enhancer)
    graph.add_node("researcher", run_researcher)
    graph.add_node("planner", run_planner)
    graph.add_node("human_review", run_human_review)
    graph.add_node("announce_outcome", announce_outcome)

    route_map = {
        "enhancer": "enhancer",
        "researcher": "researcher",
        "planner": "planner",
        "human_review": "human_review",
        "done": "announce_outcome",
    }
    graph.add_conditional_edges(START, decide_next_step, route_map)
    graph.add_conditional_edges("enhancer", decide_next_step, route_map)
    graph.add_conditional_edges("researcher", decide_next_step, route_map)
    graph.add_conditional_edges("planner", decide_next_step, route_map)
    graph.add_conditional_edges("human_review", decide_next_step, route_map)
    graph.add_edge("announce_outcome", END)

    return graph.compile(checkpointer=MemorySaver())
