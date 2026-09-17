from typing import Optional

from pydantic import BaseModel, Field


class ProposeItinerary(BaseModel):
    """Propose a specific, consistent itinerary assembled from the research results."""

    selected_flight_id: Optional[str] = Field(
        default=None, description="id of the chosen flight offer from research_results['flights']['items'], or null if flights weren't searched."
    )
    selected_stay_id: Optional[str] = Field(
        default=None,
        description="search_result_id of the chosen stay from research_results['stays']['items'], or null if stays weren't searched.",
    )
    selected_car_id: Optional[str] = Field(
        default=None, description="rate_id of the chosen car from research_results['cars']['items'], or null if cars weren't searched."
    )
    total_price: str = Field(description="Sum of the selected items' prices, as a string with currency, e.g. '$943.50'.")
    summary: str = Field(
        description="Plain-language summary of the recommended itinerary and the trade-offs considered, to show the traveler."
    )


def parse_response(response) -> dict:
    """Pure/deterministic: turn the Planner LLM's forced tool call into a plain itinerary dict."""
    if not response.tool_calls:
        raise ValueError("Planner response contained no tool call — model did not follow instructions.")
    if len(response.tool_calls) != 1:
        raise ValueError(
            f"Expected exactly one tool call from Planner, got {len(response.tool_calls)}: "
            f"{[c['name'] for c in response.tool_calls]}"
        )

    call = response.tool_calls[0]
    if call["name"] != "ProposeItinerary":
        raise ValueError(f"Unexpected tool call from Planner: {call['name']}")

    return call["args"]


def _find_item(research_results: dict, domain: str, id_field: str, id_value):
    if id_value is None:
        return None
    result = research_results.get(domain)
    if not result or result.get("status") != "ok":
        return None
    for item in result["items"]:
        if item.get(id_field) == id_value:
            return item
    return None


def validate_consistency(itinerary: dict, research_results: dict) -> list[str]:
    """Pure/deterministic: check the proposed itinerary against research_results.

    Two kinds of checks: every selected id must actually exist in the data (catches
    hallucination), and where both a flight and a stay were selected, their dates
    must actually line up. Cars aren't date-checked here — the trimmed car item
    shape doesn't carry dates at all (a known gap, see docs/pending-items.md).
    """
    problems = []

    flight = _find_item(research_results, "flights", "id", itinerary.get("selected_flight_id"))
    if itinerary.get("selected_flight_id") and flight is None:
        problems.append(f"selected_flight_id {itinerary['selected_flight_id']!r} does not exist in research_results")

    stay = _find_item(research_results, "stays", "search_result_id", itinerary.get("selected_stay_id"))
    if itinerary.get("selected_stay_id") and stay is None:
        problems.append(f"selected_stay_id {itinerary['selected_stay_id']!r} does not exist in research_results")

    car = _find_item(research_results, "cars", "rate_id", itinerary.get("selected_car_id"))
    if itinerary.get("selected_car_id") and car is None:
        problems.append(f"selected_car_id {itinerary['selected_car_id']!r} does not exist in research_results")

    if flight and stay:
        outbound_arrival = flight["slices"][0]["arriving_at"][:10]
        if outbound_arrival != stay["check_in_date"]:
            problems.append(
                f"flight arrives {outbound_arrival} but stay checks in {stay['check_in_date']} — dates don't align"
            )
        if len(flight["slices"]) > 1:
            return_departure = flight["slices"][-1]["departing_at"][:10]
            if return_departure != stay["check_out_date"]:
                problems.append(
                    f"flight returns {return_departure} but stay checks out {stay['check_out_date']} — dates don't align"
                )

    return problems
