import json
from typing import TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent

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
    model = ChatAnthropic(model="claude-sonnet-5")
    react_agent = create_react_agent(model, tools, prompt=SYSTEM_PROMPT)

    async def call_search_tools(state: ResearcherState) -> dict:
        result = await react_agent.ainvoke(
            {"messages": [HumanMessage(content=json.dumps(state["request"]))]}
        )
        return {"messages": result["messages"]}

    def extract_results_node(state: ResearcherState) -> dict:
        return {"research_results": extract_results(state["messages"])}

    def rank_node(state: ResearcherState) -> dict:
        return {"research_results": rank_and_normalize(state["research_results"])}

    def flag_node(state: ResearcherState) -> dict:
        return {"insufficient_domains": flag_insufficient(state["research_results"])}

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
