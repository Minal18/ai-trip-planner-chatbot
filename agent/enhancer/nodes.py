from typing import Literal

from pydantic import BaseModel, Field

VALID_DOMAINS = ("flights", "stays", "cars")


class AskQuestion(BaseModel):
    """Ask the traveler one clarifying question."""

    question: str = Field(description="A single, natural, conversational question.")


class RequestReady(BaseModel):
    """Declare that enough information has been gathered to proceed to search."""

    summary: str = Field(
        description="A plain-language summary of the understood trip request, to show the traveler before proceeding."
    )
    domains: list[Literal["flights", "stays", "cars"]] = Field(
        description=(
            "Which services the traveler confirmed they want: any non-empty combination of "
            "\"flights\", \"stays\" (hotel), \"cars\" (rental car). This decides exactly what gets searched."
        )
    )
    request: dict = Field(
        description=(
            "Structured fields for the domains listed in `domains` only: "
            "origin, destination, departure_date_earliest, departure_date_latest (equal to each other "
            "for an exact date), return_date (optional), adults, "
            "preferred_departure_time (morning/afternoon/evening/night/any, default \"any\"), "
            "check_in_date, check_out_date (if a stay is needed), "
            "pickup_location, pickup_date, dropoff_date, pickup_time, dropoff_time, "
            "driver_age, driver_residence_country_code (if a car is needed)."
        )
    )


def _validate_domains(domains) -> list[str]:
    """Pure/deterministic: dedupe while keeping order; reject empty or unknown values."""
    if not domains:
        raise ValueError("RequestReady must include at least one domain (flights/stays/cars).")
    unknown = [d for d in domains if d not in VALID_DOMAINS]
    if unknown:
        raise ValueError(f"RequestReady contained unknown domain(s): {unknown}")
    return list(dict.fromkeys(domains))


def parse_response(response) -> dict:
    """Pure/deterministic: turn the Enhancer LLM's forced tool call into a state update."""
    if not response.tool_calls:
        raise ValueError("Enhancer response contained no tool call — model did not follow instructions.")
    if len(response.tool_calls) != 1:
        raise ValueError(
            f"Expected exactly one tool call from Enhancer, got {len(response.tool_calls)}: "
            f"{[c['name'] for c in response.tool_calls]}"
        )

    call = response.tool_calls[0]
    if call["name"] == "RequestReady":
        domains = _validate_domains(call["args"].get("domains"))
        # Stored on the request itself (not as separate state) so it travels with
        # the request everywhere it already goes: Researcher, Planner, and the
        # Supervisor's edit path, which rewrites the whole request dict.
        return {
            "complete": True,
            "request": {**call["args"]["request"], "domains": domains},
            "summary": call["args"]["summary"],
            "pending_question": None,
        }
    elif call["name"] == "AskQuestion":
        return {
            "complete": False,
            "pending_question": call["args"]["question"],
        }
    else:
        raise ValueError(f"Unexpected tool call from Enhancer: {call['name']}")
