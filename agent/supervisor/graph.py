from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from enhancer.graph import build_enhancer_graph
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


async def build_supervisor_graph():
    enhancer_graph = build_enhancer_graph(use_own_checkpointer=False)
    researcher_graph = await build_researcher_graph()
    planner_graph = build_planner_graph()

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
            {"request": state["request"], "research_results": state["research_results"], "edit_feedback": None}
        )
        return {"itinerary": result["itinerary"]}

    def announce_itinerary(state: SupervisorState) -> dict:
        # Placeholder until Human-in-the-Loop Review exists — just surfaces
        # Planner's proposal and ends the graph, no approval gate yet.
        return {"messages": [AIMessage(content=state["itinerary"]["summary"])]}

    graph = StateGraph(SupervisorState)
    graph.add_node("enhancer", run_enhancer)
    graph.add_node("researcher", run_researcher)
    graph.add_node("planner", run_planner)
    graph.add_node("announce_itinerary", announce_itinerary)

    route_map = {"enhancer": "enhancer", "researcher": "researcher", "planner": "planner", "done": "announce_itinerary"}
    graph.add_conditional_edges(START, decide_next_step, route_map)
    graph.add_conditional_edges("enhancer", decide_next_step, route_map)
    graph.add_conditional_edges("researcher", decide_next_step, route_map)
    graph.add_conditional_edges("planner", decide_next_step, route_map)
    graph.add_edge("announce_itinerary", END)

    return graph.compile(checkpointer=MemorySaver())
