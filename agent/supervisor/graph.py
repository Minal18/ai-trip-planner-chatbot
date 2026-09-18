import json
from typing import Annotated, Optional, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from booker.graph import build_booker_graph
from enhancer.graph import build_enhancer_graph
from hitl.nodes import Approve, RequestEdits, Reject, parse_response as parse_hitl_response
from hitl.prompts import SYSTEM_PROMPT as HITL_SYSTEM_PROMPT
from planner.graph import build_planner_graph
from researcher.graph import build_researcher_graph
from supervisor.nodes import (
    NeedsEnhancer,
    NeedsPlanner,
    NeedsResearcher,
    decide_next_step,
    parse_edit_classification,
)
from supervisor.prompts import EDIT_CLASSIFICATION_PROMPT


class SupervisorState(TypedDict):
    messages: Annotated[list, add_messages]
    request: Optional[dict]
    summary: Optional[str]
    research_results: Optional[dict]
    insufficient_domains: Optional[list]
    itinerary: Optional[dict]
    itinerary_status: Optional[str]
    edit_feedback: Optional[str]
    booking_result: Optional[dict]


async def build_supervisor_graph():
    enhancer_graph = build_enhancer_graph(use_own_checkpointer=False)
    researcher_graph = await build_researcher_graph()
    planner_graph = build_planner_graph()
    booker_graph = await build_booker_graph(use_own_checkpointer=False)
    hitl_model = ChatAnthropic(model="claude-sonnet-5").bind_tools([Approve, RequestEdits, Reject], tool_choice="any")
    edit_classifier_model = ChatAnthropic(model="claude-sonnet-5").bind_tools(
        [NeedsEnhancer, NeedsResearcher, NeedsPlanner], tool_choice="any"
    )

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
        # Clear after consuming, so this round's feedback doesn't leak into a
        # later, unrelated Planner invocation.
        return {"itinerary": result["itinerary"], "edit_feedback": None}

    async def run_human_review(state: SupervisorState) -> dict:
        prompt = (
            state["itinerary"]["summary"]
            + "\n\nWould you like to approve this, ask for changes, or decline?"
        )
        reply = interrupt({"itinerary_summary": prompt})
        response = await hitl_model.ainvoke([SystemMessage(content=HITL_SYSTEM_PROMPT), HumanMessage(content=reply)])
        result = parse_hitl_response(response)
        return {**result, "messages": [HumanMessage(content=reply)]}

    async def classify_edit_feedback(state: SupervisorState) -> dict:
        payload = {
            "feedback": state["edit_feedback"],
            "current_request": state["request"],
            "research_results": state["research_results"],
        }
        response = await edit_classifier_model.ainvoke(
            [SystemMessage(content=EDIT_CLASSIFICATION_PROMPT), HumanMessage(content=json.dumps(payload))]
        )
        return parse_edit_classification(response)

    async def run_booker(state: SupervisorState) -> dict:
        result = await booker_graph.ainvoke(
            {"itinerary": state["itinerary"], "research_results": state["research_results"]}
        )
        return {"booking_result": result}

    def announce_outcome(state: SupervisorState) -> dict:
        if state["itinerary_status"] == "rejected":
            text = "No problem — let me know if you'd like to start planning a different trip."
        else:  # approved and booked (or attempted)
            text = state["booking_result"]["final_message"]
        return {"messages": [AIMessage(content=text)]}

    graph = StateGraph(SupervisorState)
    graph.add_node("enhancer", run_enhancer)
    graph.add_node("researcher", run_researcher)
    graph.add_node("planner", run_planner)
    graph.add_node("human_review", run_human_review)
    graph.add_node("classify_edit_feedback", classify_edit_feedback)
    graph.add_node("booker", run_booker)
    graph.add_node("announce_outcome", announce_outcome)

    route_map = {
        "enhancer": "enhancer",
        "researcher": "researcher",
        "planner": "planner",
        "human_review": "human_review",
        "classify_edit_feedback": "classify_edit_feedback",
        "booker": "booker",
        "done": "announce_outcome",
    }
    graph.add_conditional_edges(START, decide_next_step, route_map)
    graph.add_conditional_edges("enhancer", decide_next_step, route_map)
    graph.add_conditional_edges("researcher", decide_next_step, route_map)
    graph.add_conditional_edges("planner", decide_next_step, route_map)
    graph.add_conditional_edges("human_review", decide_next_step, route_map)
    graph.add_conditional_edges("classify_edit_feedback", decide_next_step, route_map)
    graph.add_conditional_edges("booker", decide_next_step, route_map)
    graph.add_edge("announce_outcome", END)

    return graph.compile(checkpointer=MemorySaver())
