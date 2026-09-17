from typing import Optional, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from booker.mcp_tools import load_booker_tools
from booker.nodes import (
    PassengerDetails,
    booking_id_of,
    get_selected_items,
    parse_passenger_details,
    parse_tool_output,
    price_changed_materially,
    reference_of,
)
from booker.prompts import PASSENGER_EXTRACTION_PROMPT


class ConfirmAtNewPrice(BaseModel):
    """The traveler accepts the new price(s) and wants to proceed with booking."""


class CancelDueToPriceChange(BaseModel):
    """The traveler does not accept the new price(s) — don't book anything."""


class BookerState(TypedDict):
    itinerary: dict
    research_results: dict
    passenger: Optional[dict]
    resolved_stay_rate_id: Optional[str]
    needs_reconfirm: Optional[bool]
    reprice_summary: Optional[str]
    reconfirmed: Optional[bool]
    booking_results: Optional[dict]
    final_message: Optional[str]


async def build_booker_graph(use_own_checkpointer: bool = True):
    """use_own_checkpointer=True: standalone use (tests) — this graph manages its
    own pause/resume. Set False when nesting this graph as a node inside a parent
    graph (e.g. Supervisor) — same reasoning as Enhancer's build_enhancer_graph."""
    tools = await load_booker_tools()
    passenger_model = ChatAnthropic(model="claude-sonnet-5").bind_tools([PassengerDetails], tool_choice="any")
    reconfirm_model = ChatAnthropic(model="claude-sonnet-5").bind_tools(
        [ConfirmAtNewPrice, CancelDueToPriceChange], tool_choice="any"
    )

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

    async def reprice_offers(state: BookerState) -> dict:
        selected = get_selected_items(state["itinerary"], state["research_results"])
        changed = False
        summary_lines = []
        resolved_stay_rate_id = None

        if selected["flight"]:
            fresh = parse_tool_output(await tools["get_offer"].ainvoke({"offer_id": selected["flight"]["id"]}))
            if "error" in fresh:
                changed = True
                summary_lines.append(f"Flight: could not re-verify ({fresh['error']}) — treating as changed.")
            else:
                old_price = selected["flight"]["total_amount"]
                new_price = fresh.get("total_amount")
                if price_changed_materially(old_price, new_price):
                    changed = True
                    summary_lines.append(f"Flight: was ${old_price}, now ${new_price}.")

        if selected["stay"]:
            fresh = parse_tool_output(
                await tools["get_stay_rate"].ainvoke({"search_result_id": selected["stay"]["search_result_id"]})
            )
            if "error" in fresh or not fresh.get("rates"):
                changed = True
                summary_lines.append("Stay: could not re-verify rates — treating as changed.")
            else:
                cheapest = min(fresh["rates"], key=lambda r: float(r["total_amount"]))
                resolved_stay_rate_id = cheapest["rate_id"]
                old_price = selected["stay"]["cheapest_rate_total_amount"]
                new_price = cheapest["total_amount"]
                if price_changed_materially(old_price, new_price):
                    changed = True
                    summary_lines.append(f"Stay: was ${old_price}, now ${new_price}.")

        # Cars have no reprice tool — booked directly at the originally-shown price.

        return {
            "needs_reconfirm": changed,
            "reprice_summary": " ".join(summary_lines) if summary_lines else None,
            "resolved_stay_rate_id": resolved_stay_rate_id,
        }

    async def reconfirm(state: BookerState) -> dict:
        reply = interrupt(
            {"question": f"Prices changed before booking: {state['reprice_summary']} Proceed anyway, or cancel?"}
        )
        response = await reconfirm_model.ainvoke([HumanMessage(content=reply)])
        if not response.tool_calls:
            raise ValueError("Reconfirm response contained no tool call")
        return {"reconfirmed": response.tool_calls[0]["name"] == "ConfirmAtNewPrice"}

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

        if itinerary.get("selected_stay_id") and state.get("resolved_stay_rate_id"):
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
        if state.get("reconfirmed") is False:
            return {"final_message": "Booking cancelled — prices changed and you didn't want to proceed at the new price."}

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

    def route_after_reprice(state: BookerState) -> str:
        return "reconfirm" if state["needs_reconfirm"] else "book"

    def route_after_reconfirm(state: BookerState) -> str:
        return "book" if state["reconfirmed"] else "compile_result"

    def route_after_book(state: BookerState) -> str:
        results = state["booking_results"]
        failed = [d for d, r in results.items() if "error" in r]
        succeeded = [d for d, r in results.items() if "error" not in r]
        return "compensate_if_needed" if (failed and succeeded) else "compile_result"

    graph = StateGraph(BookerState)
    graph.add_node("collect_passenger_details", collect_passenger_details)
    graph.add_node("reprice_offers", reprice_offers)
    graph.add_node("reconfirm", reconfirm)
    graph.add_node("book", book)
    graph.add_node("compensate_if_needed", compensate_if_needed)
    graph.add_node("compile_result", compile_result)

    graph.add_edge(START, "collect_passenger_details")
    graph.add_edge("collect_passenger_details", "reprice_offers")
    graph.add_conditional_edges("reprice_offers", route_after_reprice, {"reconfirm": "reconfirm", "book": "book"})
    graph.add_conditional_edges(
        "reconfirm", route_after_reconfirm, {"book": "book", "compile_result": "compile_result"}
    )
    graph.add_conditional_edges(
        "book", route_after_book, {"compensate_if_needed": "compensate_if_needed", "compile_result": "compile_result"}
    )
    graph.add_edge("compensate_if_needed", "compile_result")
    graph.add_edge("compile_result", END)

    return graph.compile(checkpointer=MemorySaver() if use_own_checkpointer else None)
