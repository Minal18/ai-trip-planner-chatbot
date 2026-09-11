"""
Level 1: compiles the real Researcher subgraph and invokes it against real LLM +
MCP tool calls. This costs API credits and hits live (test-mode) Duffel endpoints —
run manually, not as part of an automated suite:

    python3 tests/test_researcher_subgraph.py
"""

import asyncio
import json

from dotenv import load_dotenv

from researcher.graph import build_researcher_graph

load_dotenv()


async def run_case(graph, label: str, request: dict):
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
    result = await graph.ainvoke({"request": request})

    print("\n--- Final message ---")
    print(result["messages"][-1].content)

    print("\n--- research_results ---")
    print(json.dumps(result["research_results"], indent=2))

    print("\n--- insufficient_domains ---")
    print(result["insufficient_domains"])


async def main():
    graph = await build_researcher_graph()

    await run_case(
        graph,
        "Flights only",
        {"origin": "SEA", "destination": "HNL", "departure_date": "2026-11-15", "adults": 1},
    )

    await run_case(
        graph,
        "Flights + Stays (stays should come back as an 'unavailable' error, not silently dropped)",
        {
            "origin": "SEA",
            "destination": "HNL",
            "departure_date": "2026-11-15",
            "adults": 1,
            "check_in_date": "2026-11-15",
            "check_out_date": "2026-11-18",
        },
    )

    await run_case(
        graph,
        "Cars only (should call search_cars, not flights/stays)",
        {
            "pickup_location": "Honolulu",
            "pickup_date": "2026-11-15",
            "dropoff_date": "2026-11-18",
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
