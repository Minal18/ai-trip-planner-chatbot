import json

from pydantic import BaseModel, Field


class PassengerDetails(BaseModel):
    """Extracted passenger/traveler contact and identity details needed for booking."""

    given_name: str
    family_name: str
    email: str
    phone_number: str = Field(description="E.164 format, e.g. +14155550123")
    date_of_birth: str = Field(description="ISO date string, YYYY-MM-DD")
    title: str = Field(description='One of: "mr", "ms", "mrs", "miss", "dr" — as the traveler stated, never guessed.')
    gender: str = Field(description='"m" or "f" — as the traveler stated, never inferred from their name.')


def parse_passenger_details(response) -> dict:
    """Pure/deterministic: turn the passenger-extraction LLM's forced tool call into a plain dict."""
    if not response.tool_calls:
        raise ValueError("Passenger details response contained no tool call — model did not follow instructions.")
    if len(response.tool_calls) != 1:
        raise ValueError(f"Expected exactly one tool call, got {len(response.tool_calls)}")

    call = response.tool_calls[0]
    if call["name"] != "PassengerDetails":
        raise ValueError(f"Unexpected tool call: {call['name']}")
    return call["args"]


def parse_tool_output(content) -> dict:
    """Same content-block unwrapping as Researcher's extract_results — direct
    tool.ainvoke() calls return the same langchain-mcp-adapters wrapped shape."""
    if isinstance(content, list):
        text_parts = [
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "".join(text_parts) if text_parts else str(content)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {"error": content}
    if isinstance(content, dict):
        return content
    return {"error": str(content)}


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


def get_selected_items(itinerary: dict, research_results: dict) -> dict:
    """Pure: look up the full trimmed research item for each domain the itinerary selected."""
    return {
        "flight": _find_item(research_results, "flights", "id", itinerary.get("selected_flight_id")),
        "stay": _find_item(research_results, "stays", "search_result_id", itinerary.get("selected_stay_id")),
        "car": _find_item(research_results, "cars", "rate_id", itinerary.get("selected_car_id")),
    }


def booking_id_of(result: dict):
    """Pure: flights' book_flight returns order_id; stays/cars' book_* return
    booking_id — this normalizes the lookup so callers don't need to know which."""
    return result.get("booking_id") or result.get("order_id")


def reference_of(result: dict):
    """Pure: flights' book_flight returns booking_reference; stays/cars' book_*
    return reference — this normalizes the lookup so callers don't need to know which."""
    return result.get("reference") or result.get("booking_reference")
