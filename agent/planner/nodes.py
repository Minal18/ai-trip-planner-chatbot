from datetime import date, datetime, timedelta
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
    summary: str = Field(
        description=(
            "2-3 short sentences, max ~60 words: why these picks fit the traveler's preferences and the one "
            "key trade-off, if any. Don't restate prices, times, flight legs, or dates (they're shown to the "
            "traveler separately), and don't discuss date mismatches (flagged separately)."
        )
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


# A flight landing before this hour still needs a room the night before (a red-eye
# landing at 03:19 needs the bed held from the previous night's check-in), and a
# return departing before EARLY_DEPARTURE_HOUR means leaving the hotel/car the evening before.
NEEDS_PRIOR_NIGHT_BEFORE_HOUR = 12
EARLY_DEPARTURE_HOUR = 6


def _dt(value: str) -> datetime:
    # Duffel gives local times without an offset ("2026-12-26T03:19:00"); stay/car
    # dates are local to the destination too, so naive local comparison is right.
    return datetime.fromisoformat(value[:19])


def _d(value: str) -> date:
    return date.fromisoformat(value[:10])


def _fmt(d: date) -> str:
    return d.strftime("%-d %b")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def check_dates(itinerary: dict, research_results: dict) -> tuple[list[str], list[str]]:
    """Pure/deterministic: compare the selected stay/car dates with the flight's
    actual (local) arrival and return-departure times.

    Returns (problems, notes). Problems are real conflicts — no room or car when
    you land, a stay/car that runs past your return flight — which the Planner
    retries on (often a different flight fixes it). Notes are workable but worth
    telling the traveler (e.g. paying for a night before a long-haul flight lands);
    they never trigger a retry, since re-picking can't change searched dates.

    Arrival can cross 1-2 days (red-eyes, long-haul): a stay is aligned anywhere
    from the night before an early-morning landing through the landing date.
    """
    problems: list[str] = []
    notes: list[str] = []
    flight = _find_item(research_results, "flights", "id", itinerary.get("selected_flight_id"))
    if not flight or not flight.get("slices"):
        return problems, notes
    stay = _find_item(research_results, "stays", "search_result_id", itinerary.get("selected_stay_id"))
    car = _find_item(research_results, "cars", "rate_id", itinerary.get("selected_car_id"))

    departs = _dt(flight["slices"][0]["departing_at"])
    lands = _dt(flight["slices"][0]["arriving_at"])
    first_night = lands.date() - timedelta(days=1) if lands.hour < NEEDS_PRIOR_NIGHT_BEFORE_HOUR else lands.date()
    landing = f"you land {_fmt(lands.date())} at {lands:%H:%M}"
    if lands.date() > departs.date():
        landing += f" ({_plural((lands.date() - departs.date()).days, 'day')} after departing)"

    returns = _dt(flight["slices"][-1]["departing_at"]) if len(flight["slices"]) > 1 else None
    # The last day you still need the room/car: an early-morning return means
    # you leave the evening before, so either that day or the day before is fine.
    leave_by = returns.date() if returns else None
    leave_from = (
        returns.date() - timedelta(days=1) if returns and returns.hour < EARLY_DEPARTURE_HOUR else leave_by
    )

    if stay:
        check_in, check_out = _d(stay["check_in_date"]), _d(stay["check_out_date"])
        if check_in > lands.date():
            problems.append(
                f"{landing} but the stay only starts {_fmt(check_in)} — no room for your first "
                f"{_plural((check_in - lands.date()).days, 'night')}"
            )
        elif check_in < departs.date():
            problems.append(f"the stay starts {_fmt(check_in)}, before your flight departs {_fmt(departs.date())}")
        elif check_in < first_night:
            notes.append(
                f"Hotel check-in is {_fmt(check_in)} but {landing} — you'll pay for "
                f"{_plural((first_night - check_in).days, 'night')} before you arrive."
            )
        if returns:
            if check_out > leave_by:
                problems.append(
                    f"the stay checks out {_fmt(check_out)}, after your return flight leaves {_fmt(leave_by)}"
                )
            elif check_out < leave_from:
                problems.append(
                    f"the stay checks out {_fmt(check_out)} but your return flight leaves "
                    f"{_fmt(returns.date())} at {returns:%H:%M} — no room for the last "
                    f"{_plural((leave_from - check_out).days, 'night')}"
                )

    if car:
        pickup, dropoff = _d(car["pickup_date"]), _d(car["dropoff_date"])
        if pickup < lands.date():
            # Can't collect a car before landing; agencies may cancel it as a no-show.
            problems.append(
                f"car pickup is {_fmt(pickup)} but {landing} — the rental could be cancelled as a no-show "
                f"(pickup should be {_fmt(lands.date())})"
            )
        elif pickup > lands.date():
            notes.append(
                f"Car pickup is {_fmt(pickup)}, {_plural((pickup - lands.date()).days, 'day')} after you land."
            )
        if returns:
            if dropoff > leave_by:
                problems.append(
                    f"the car is due back {_fmt(dropoff)}, after your return flight leaves {_fmt(leave_by)}"
                )
            elif dropoff < leave_from:
                notes.append(
                    f"The car is due back {_fmt(dropoff)}, {_plural((leave_from - dropoff).days, 'day')} "
                    f"before your return flight."
                )

    return problems, notes


def validate_consistency(itinerary: dict, research_results: dict) -> list[str]:
    """Pure/deterministic: check the proposed itinerary against research_results.

    Every selected id must actually exist in the data (catches hallucination), and
    the stay/car dates must work with the flight's real arrival/return times (see
    check_dates — only its blocking problems are returned here).
    """
    problems = []
    for key, domain, id_field in (
        ("selected_flight_id", "flights", "id"),
        ("selected_stay_id", "stays", "search_result_id"),
        ("selected_car_id", "cars", "rate_id"),
    ):
        if itinerary.get(key) and _find_item(research_results, domain, id_field, itinerary[key]) is None:
            problems.append(f"{key} {itinerary[key]!r} does not exist in research_results")

    problems.extend(check_dates(itinerary, research_results)[0])
    return problems


# Where each domain's selected id and whole-trip price live in research_results.
_DOMAIN_FIELDS = {
    "flights": ("selected_flight_id", "id", "total_amount", "total_currency"),
    "stays": ("selected_stay_id", "search_result_id", "cheapest_rate_total_amount", "cheapest_rate_currency"),
    "cars": ("selected_car_id", "rate_id", "total_amount", "total_currency"),
}


def compute_total(itinerary: dict, research_results: dict) -> str:
    """Pure/deterministic: sum the selected items' whole-trip prices (taxes included),
    per currency. Done in code, not by the LLM, so the total is always exactly the
    sum of what's shown. Mixed currencies are listed side by side rather than
    converted, e.g. "USD 1,022.21 + EUR 300.00"."""
    totals: dict[str, float] = {}
    for domain, (selection_key, id_field, amount_field, currency_field) in _DOMAIN_FIELDS.items():
        item = _find_item(research_results, domain, id_field, itinerary.get(selection_key))
        if item is None or item.get(amount_field) is None:
            continue
        currency = item.get(currency_field) or "USD"
        totals[currency] = totals.get(currency, 0.0) + float(item[amount_field])
    if not totals:
        return "n/a"
    return " + ".join(f"{cur} {amount:,.2f}" for cur, amount in totals.items())
