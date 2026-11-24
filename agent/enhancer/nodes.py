import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

VALID_DOMAINS = ("flights", "stays", "cars")


class AskQuestion(BaseModel):
    """Ask the traveler one clarifying question."""

    question: str = Field(description="A single, natural, conversational question.")


class Preferences(BaseModel):
    """Comfort/budget preferences, per domain. Every default means "no preference
    stated: go for best value", which is not the same as "cheapest at any cost"."""

    flight_cabin: Literal["economy", "premium_economy", "business", "first"] = Field(
        default="economy", description="Cabin class for flights."
    )
    flight_max_stops: Optional[int] = Field(
        default=None, description="Maximum stops per direction (0 = nonstop, 1 = up to one stop). null = no limit."
    )
    stay_tier: Literal["any", "budget", "midrange", "luxury"] = Field(
        default="any", description="Hotel comfort level. \"any\" = best value."
    )
    car_class: Literal["any", "economy", "compact", "midsize", "fullsize", "suv", "minivan", "premium"] = Field(
        default="any", description="Rental car size/class. \"premium\" covers luxury and convertibles. \"any\" = best value."
    )
    budget_note: Optional[str] = Field(
        default=None, description="Any overall budget the traveler stated, in their words (e.g. \"around $4,000 total\")."
    )


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
    preferences: Preferences = Field(
        default_factory=Preferences,
        description="The traveler's comfort/budget preferences for the chosen services. Leave a field at its default if they didn't state one.",
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
            "request": {
                **call["args"]["request"],
                "domains": domains,
                # Validated here (fills defaults, rejects unknown values) so every
                # downstream agent can rely on the full preferences shape.
                "preferences": Preferences.model_validate(call["args"].get("preferences") or {}).model_dump(),
            },
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


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _next_occurrence(d: date, today: date) -> date:
    while d < today:
        try:
            d = d.replace(year=d.year + 1)
        except ValueError:  # 29 Feb -> a non-leap year
            d = d.replace(year=d.year + 1, day=28)
    return d


def roll_past_dates_forward(value, today: date):
    """Pure/deterministic backstop for a wrong year: move any trip date field (a
    key containing "date" — but never a birth date — ISO YYYY-MM-DD) that's before
    today to its next occurrence.

    A trip date in the past is never what the traveler meant — it's the model
    filling in the current year for "Jan 15th" when it's already November, which
    the provider then rejects ("departure_date must be after <today>"). Each date
    rolls independently, so a mis-yeared return ("Dec 28 – Jan 3") lands in the
    following year, after the departure. Walks nested dicts/lists.
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = k.lower()
            is_trip_date = "date" in key and "birth" not in key and "born" not in key
            if isinstance(v, str) and is_trip_date and _ISO_DATE.match(v):
                out[k] = _next_occurrence(date.fromisoformat(v), today).isoformat()
            else:
                out[k] = roll_past_dates_forward(v, today)
        return out
    if isinstance(value, list):
        return [roll_past_dates_forward(v, today) for v in value]
    return value

