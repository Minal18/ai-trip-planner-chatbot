from typing import Optional, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from booker.mcp_tools import load_booker_tools
from booker.nodes import (
    PassengerDetails,
    booking_id_of,
    get_selected_items,
    parse_passenger_details,
    parse_tool_output,
    reference_of,
)
from booker.prompts import PASSENGER_EXTRACTION_PROMPT


class BookerState(TypedDict):
    itinerary: dict
    research_results: dict
    passenger: Optional[dict]
    resolved_stay_rate_id: Optional[str]
    booking_results: Optional[dict]
    final_message: Optional[str]


async def build_booker_graph(use_own_checkpointer: bool = True):
    """use_own_checkpointer=True: standalone use (tests) — this graph manages its
    own pause/resume. Set False when nesting this graph as a node inside a parent
    graph (e.g. Supervisor) — same reasoning as Enhancer's build_enhancer_graph."""
    tools = await load_booker_tools()
    passenger_model = ChatAnthropic(model="claude-sonnet-5").bind_tools([PassengerDetails], tool_choice="any")

    async def collect_passenger_details(state: BookerState) -> dict:
        reply = interrupt(
            {
                "question": "To book this, I need your full legal name, email, phone number, "
                "date of birth, title (Mr/Ms/Mrs/Miss/Dr), and gender."
            }
        )
        response = await passenger_model.ainvoke(
            [SystemMessage(content=PASSENGER_EXTRACTION_PROMPT), HumanMessage(content=reply)]
        )
        return {"passenger": parse_passenger_details(response)}

    async def resolve_stay_rate(state: BookerState) -> dict:
        # Not a reprice check — itinerary only recorded a search_result_id (an
        # accommodation), not a bookable rate_id. book_stay needs a real rate_id,
        # which only get_stay_rate can produce. Duffel's own booking call already
        # rejects a stale/expired rate cleanly, so there's no separate price
        # comparison here — see the conversation that led to simplifying this.
        selected = get_selected_items(state["itinerary"], state["research_results"])
        if not selected["stay"]:
            return {}

        fresh = parse_tool_output(
            await tools["get_stay_rate"].ainvoke({"search_result_id": selected["stay"]["search_result_id"]})
        )
        if "error" in fresh or not fresh.get("rates"):
            return {"resolved_stay_rate_id": None}

        cheapest = min(fresh["rates"], key=lambda r: float(r["total_amount"]))
        return {"resolved_stay_rate_id": cheapest["rate_id"]}

    async def book(state: BookerState) -> dict:
        itinerary = state["itinerary"]
        p = state["passenger"]
        results = {}

        if itinerary.get("selected_flight_id"):
            result = parse_tool_output(
                await tools["book_flight"].ainvoke(
                    {
                        "offer_id": itinerary["selected_flight_id"],
                        "passenger_given_name": p["given_name"],
                        "passenger_family_name": p["family_name"],
                        "passenger_email": p["email"],
                        "passenger_born_on": p["date_of_birth"],
                        "passenger_gender": p["gender"],
                        "passenger_title": p["title"],
                        "passenger_phone_number": p["phone_number"],
                    }
                )
            )
            results["flight"] = result

        if itinerary.get("selected_stay_id"):
            if not state.get("resolved_stay_rate_id"):
                results["stay"] = {"error": "Could not resolve a bookable rate for the selected stay."}
            else:
                result = parse_tool_output(
                    await tools["book_stay"].ainvoke(
                        {
                            "rate_id": state["resolved_stay_rate_id"],
                            "guest_given_name": p["given_name"],
                            "guest_family_name": p["family_name"],
                            "guest_email": p["email"],
                            "guest_phone_number": p["phone_number"],
                        }
                    )
                )
                results["stay"] = result

        if itinerary.get("selected_car_id"):
            result = parse_tool_output(
                await tools["book_car"].ainvoke(
                    {
                        "rate_id": itinerary["selected_car_id"],
                        "driver_given_name": p["given_name"],
                        "driver_family_name": p["family_name"],
                        "driver_date_of_birth": p["date_of_birth"],
                        "driver_email": p["email"],
                        "driver_phone_number": p["phone_number"],
                    }
                )
            )
            results["car"] = result

        return {"booking_results": results}

    async def compensate_if_needed(state: BookerState) -> dict:
        results = state["booking_results"]
        failed = [d for d, r in results.items() if "error" in r]
        succeeded = [d for d, r in results.items() if "error" not in r]
        if not failed or not succeeded:
            return {}

        cancel_tool = {"flight": "cancel_booking", "stay": "cancel_stay_booking", "car": "cancel_car_booking"}
        for domain in succeeded:
            await tools[cancel_tool[domain]].ainvoke({"booking_id": booking_id_of(results[domain])})
            results[domain]["status"] = "cancelled (compensating for partial failure)"
        return {"booking_results": results}

    def compile_result(state: BookerState) -> dict:
        results = state.get("booking_results") or {}
        if not results:
            return {"final_message": "Nothing was booked."}

        failed = [d for d, r in results.items() if "error" in r]
        lines = []
        for domain, r in results.items():
            if "error" in r:
                lines.append(f"- {domain}: FAILED ({r['error']})")
            else:
                lines.append(f"- {domain}: confirmed, reference {reference_of(r) or booking_id_of(r)}")
        if failed:
            lines.append("\nSome bookings failed — anything that did succeed was cancelled to avoid a stranded partial trip.")
        return {"final_message": "\n".join(lines)}

    def route_after_book(state: BookerState) -> str:
        results = state["booking_results"]
        failed = [d for d, r in results.items() if "error" in r]
        succeeded = [d for d, r in results.items() if "error" not in r]
        return "compensate_if_needed" if (failed and succeeded) else "compile_result"

    graph = StateGraph(BookerState)
    graph.add_node("collect_passenger_details", collect_passenger_details)
    graph.add_node("resolve_stay_rate", resolve_stay_rate)
    graph.add_node("book", book)
    graph.add_node("compensate_if_needed", compensate_if_needed)
    graph.add_node("compile_result", compile_result)

    graph.add_edge(START, "collect_passenger_details")
    graph.add_edge("collect_passenger_details", "resolve_stay_rate")
    graph.add_edge("resolve_stay_rate", "book")
    graph.add_conditional_edges(
        "book", route_after_book, {"compensate_if_needed": "compensate_if_needed", "compile_result": "compile_result"}
    )
    graph.add_edge("compensate_if_needed", "compile_result")
    graph.add_edge("compile_result", END)

    return graph.compile(checkpointer=MemorySaver() if use_own_checkpointer else None)
