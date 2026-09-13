from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from enhancer.graph import build_enhancer_graph
from researcher.graph import build_researcher_graph
from supervisor.nodes import decide_next_step


class SupervisorState(TypedDict):
    messages: Annotated[list, add_messages]
    request: Optional[dict]
    summary: Optional[str]
    research_results: Optional[dict]
    insufficient_domains: Optional[list]


async def build_supervisor_graph():
    enhancer_graph = build_enhancer_graph(use_own_checkpointer=False)
    researcher_graph = await build_researcher_graph()

    async def run_enhancer(state: SupervisorState) -> dict:
        result = await enhancer_graph.ainvoke({"messages": state["messages"]})
        return {"request": result["request"], "summary": result["summary"]}

    async def run_researcher(state: SupervisorState) -> dict:
        result = await researcher_graph.ainvoke({"request": state["request"]})
        return {
            "research_results": result["research_results"],
            "insufficient_domains": result["insufficient_domains"],
        }

    def run_planner_stub(state: SupervisorState) -> dict:
        # Placeholder until the real Planner agent exists — just formats what
        # Researcher found into a readable message and ends the graph.
        lines = [f"Here's what I found for your trip: {state['summary']}", ""]
        for domain, result in state["research_results"].items():
            if result["status"] == "error":
                lines.append(f"- {domain}: unavailable ({result['error']})")
            else:
                lines.append(f"- {domain}: {len(result['items'])} option(s) found")
        return {"messages": [AIMessage(content="\n".join(lines))]}

    graph = StateGraph(SupervisorState)
    graph.add_node("enhancer", run_enhancer)
    graph.add_node("researcher", run_researcher)
    graph.add_node("planner_stub", run_planner_stub)

    route_map = {"enhancer": "enhancer", "researcher": "researcher", "done": "planner_stub"}
    graph.add_conditional_edges(START, decide_next_step, route_map)
    graph.add_conditional_edges("enhancer", decide_next_step, route_map)
    graph.add_conditional_edges("researcher", decide_next_step, route_map)
    graph.add_edge("planner_stub", END)

    return graph.compile(checkpointer=MemorySaver())
