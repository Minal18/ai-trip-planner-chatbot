import json
from typing import Optional, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from planner.nodes import ProposeItinerary, parse_response, validate_consistency
from planner.prompts import SYSTEM_PROMPT


class PlannerState(TypedDict):
    request: dict
    research_results: dict
    edit_feedback: Optional[str]
    itinerary: Optional[dict]
    unresolved_issues: Optional[list[str]]
    retry_count: int


def build_planner_graph():
    model = ChatAnthropic(model="claude-sonnet-5").bind_tools([ProposeItinerary], tool_choice="any")

    async def generate_itinerary(state: PlannerState) -> dict:
        payload = {
            "request": state["request"],
            "research_results": state["research_results"],
            "edit_feedback": state.get("edit_feedback"),
        }
        messages = [HumanMessage(content=json.dumps(payload))]
        if state.get("unresolved_issues"):
            messages.append(
                HumanMessage(
                    content=(
                        "Your previous selection had these problems — fix them: "
                        + "; ".join(state["unresolved_issues"])
                    )
                )
            )

        response = await model.ainvoke([SystemMessage(content=SYSTEM_PROMPT)] + messages)
        itinerary = parse_response(response)
        problems = validate_consistency(itinerary, state["research_results"])

        return {
            "itinerary": itinerary,
            "unresolved_issues": problems,
            "retry_count": state.get("retry_count", 0) + 1,
        }

    def route(state: PlannerState) -> str:
        # Bounded: one retry only, not a full escalation back to Researcher —
        # see docs/pending-items.md for the deferred full-escalation path.
        if state["unresolved_issues"] and state["retry_count"] < 2:
            return "retry"
        return "done"

    graph = StateGraph(PlannerState)
    graph.add_node("generate_itinerary", generate_itinerary)
    graph.add_edge(START, "generate_itinerary")
    graph.add_conditional_edges("generate_itinerary", route, {"retry": "generate_itinerary", "done": END})

    return graph.compile()
