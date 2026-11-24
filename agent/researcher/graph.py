import asyncio
import json
from typing import TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from researcher.mcp_tools import load_researcher_tools
from researcher.nodes import extract_results, flag_insufficient, rank_and_normalize
from researcher.prompts import SYSTEM_PROMPT


class ResearcherState(TypedDict):
    messages: list
    request: dict
    research_results: dict
    insufficient_domains: list[str]


async def build_researcher_graph():
    tools = await load_researcher_tools()
    # tool_choice="any": the one call must request searches, never answer in prose.
    model = ChatAnthropic(model="claude-sonnet-5").bind_tools(tools, tool_choice="any")
    # Cached across Researcher runs in a conversation (e.g. a re-search after an
    # edit), since this prompt is a constant. 5-minute TTL, same as Enhancer.
    cached_prompt = SystemMessage(
        content=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "5m"}}]
    )
    tools_by_name = {t.name: t for t in tools}

    async def run_tool_call(call: dict) -> ToolMessage:
        """A failing (or unknown) tool becomes an error ToolMessage, which
        extract_results records as that domain's error — never a crash."""
        try:
            tool = tools_by_name[call["name"]]
            return await tool.ainvoke({**call, "type": "tool_call"})
        except Exception as e:
            return ToolMessage(
                content=json.dumps({"error": str(e)}),
                name=call["name"],
                tool_call_id=call["id"],
                status="error",
            )

    async def call_search_tools(state: ResearcherState) -> dict:
        # Exactly one LLM call: pick every search at once, then run them in code.
        # Deliberately NOT a ReAct loop — its second LLM call only wrote a prose
        # summary of the results (~1k output tokens, ~9s per trace) that nothing
        # downstream read: extract_results parses the ToolMessages directly, and
        # Planner/HITL present the results to the traveler.
        request_message = HumanMessage(content=json.dumps(state["request"]))
        ai_message = await model.ainvoke([cached_prompt, request_message])
        # Independent searches (flights/stays/cars, or one flight search per date
        # in a flexible window) run concurrently.
        tool_messages = await asyncio.gather(*(run_tool_call(c) for c in ai_message.tool_calls))
        return {"messages": [request_message, ai_message, *tool_messages]}

    def extract_results_node(state: ResearcherState) -> dict:
        return {"research_results": extract_results(state["messages"])}

    def rank_node(state: ResearcherState) -> dict:
        preferred = state["request"].get("preferred_departure_time", "any")
        return {
            "research_results": rank_and_normalize(
                state["research_results"],
                preferred_departure_time=preferred,
                preferences=state["request"].get("preferences"),
            )
        }

    def flag_node(state: ResearcherState) -> dict:
        return {
            "insufficient_domains": flag_insufficient(
                state["research_results"], requested_domains=state["request"].get("domains")
            )
        }

    graph = StateGraph(ResearcherState)
    graph.add_node("call_search_tools", call_search_tools)
    graph.add_node("extract_results", extract_results_node)
    graph.add_node("rank_and_normalize", rank_node)
    graph.add_node("flag_insufficient", flag_node)

    graph.add_edge(START, "call_search_tools")
    graph.add_edge("call_search_tools", "extract_results")
    graph.add_edge("extract_results", "rank_and_normalize")
    graph.add_edge("rank_and_normalize", "flag_insufficient")
    graph.add_edge("flag_insufficient", END)

    return graph.compile()
