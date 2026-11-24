from datetime import date, datetime

from pydantic import BaseModel, Field


class Approve(BaseModel):
    """The traveler approves the itinerary as presented and wants to proceed."""


class RequestEdits(BaseModel):
    """The traveler wants something changed before proceeding."""

    feedback: str = Field(description="The traveler's edit request, capturing their actual intent.")


class Reject(BaseModel):
    """The traveler does not want to proceed with this trip at all — not just a
    change to one part of it (that's RequestEdits), but declining the trip entirely."""


def parse_response(response) -> dict:
    """Pure/deterministic: turn the HITL classification LLM's forced tool call into a state update."""
    if not response.tool_calls:
        raise ValueError("HITL response contained no tool call — model did not follow instructions.")
    if len(response.tool_calls) != 1:
        raise ValueError(
            f"Expected exactly one tool call from HITL classification, got {len(response.tool_calls)}: "
            f"{[c['name'] for c in response.tool_calls]}"
        )

    call = response.tool_calls[0]
    if call["name"] == "Approve":
        return {"itinerary_status": "approved", "edit_feedback": None}
    elif call["name"] == "RequestEdits":
        return {"itinerary_status": "edit_requested", "edit_feedback": call["args"]["feedback"]}
    elif call["name"] == "Reject":
        return {"itinerary_status": "rejected", "edit_feedback": None}
    else:
        raise ValueError(f"Unexpected tool call from HITL classification: {call['name']}")


# --- Review card ---------------------------------------------------------------
# Everything factual the traveler sees (legs, dates, prices, totals) is rendered
# here from research_results, in code, so it's always exact and compact. The
# Planner's own text is limited to a short "why these picks" summary.


def _find(research_results: dict, domain: str, id_field: str, id_value):
    result = research_results.get(domain) or {}
    if id_value is None or result.get("status") != "ok":
        return None
    return next((item for item in result["items"] if item.get(id_field) == id_value), None)


def _fmt_dt(iso: str) -> str:
    """'2026-11-26T19:21:00' -> 'Nov 26 19:21'"""
    dt = datetime.fromisoformat(iso[:19])
    return f"{dt:%b} {dt.day} {dt:%H:%M}"


def _fmt_date(iso: str) -> str:
    """'2026-11-26' -> 'Nov 26'"""
    d = date.fromisoformat(iso[:10])
    return f"{d:%b} {d.day}"


def _fmt_minutes(minutes: int) -> str:
    hours, mins = divmod(int(minutes), 60)
    return f"{hours}h {mins:02d}m" if hours else f"{mins}m"


def _fmt_money(amount, currency: str | None) -> str:
    try:
        return f"{currency or 'USD'} {float(amount):,.2f}"
    except (TypeError, ValueError):
        return "price n/a"


def _flight_lines(flight: dict) -> list[str]:
    cabin = (flight.get("cabin_class") or "economy").replace("_", " ").title()
    lines = [
        f"**Flight** · {flight.get('airline')} · {cabin} · "
        f"{_fmt_money(flight.get('total_amount'), flight.get('total_currency'))} (all travelers, incl. taxes)"
    ]
    for s in flight.get("slices", []):
        stops = s.get("stops", max(len(s.get("segments", [])) - 1, 0))
        stops_text = "nonstop" if stops == 0 else f"{stops} stop" + ("s" if stops > 1 else "")
        lines.append(
            f"- **{s['origin']} → {s['destination']}** · {stops_text} · "
            f"{_fmt_dt(s['departing_at'])} → {_fmt_dt(s['arriving_at'])}"
        )
        segments = s.get("segments") or []
        if len(segments) > 1:  # only spell out legs when there's a connection
            for i, seg in enumerate(segments):
                if i > 0:
                    layover = datetime.fromisoformat(seg["departing_at"][:19]) - datetime.fromisoformat(
                        segments[i - 1]["arriving_at"][:19]
                    )
                    lines.append(f"    - layover {_fmt_minutes(layover.total_seconds() // 60)} in {seg['origin']}")
                number = f"{seg['flight_number']} " if seg.get("flight_number") else ""
                lines.append(
                    f"    - {number}{seg['origin']} {_fmt_dt(seg['departing_at'])}"
                    f" → {seg['destination']} {_fmt_dt(seg['arriving_at'])}"
                )
    return lines


def _stay_lines(stay: dict) -> list[str]:
    rating = f" ({stay['rating']}★)" if stay.get("rating") is not None else ""
    currency = stay.get("cheapest_rate_currency")
    price = _fmt_money(stay.get("cheapest_rate_total_amount"), currency)
    if stay.get("nights") and stay.get("nightly_rate"):
        breakdown = f"{stay['nights']} nights × {_fmt_money(stay['nightly_rate'], currency)}"
        if stay.get("taxes_amount"):
            breakdown += f" + {_fmt_money(stay['taxes_amount'], currency)} taxes"
        price = f"{breakdown} = {price}"
    return [
        f"**Hotel** · {stay.get('accommodation_name')}{rating}",
        f"- {_fmt_date(stay['check_in_date'])} → {_fmt_date(stay['check_out_date'])} · {price}",
    ]


def _car_lines(car: dict) -> list[str]:
    currency = car.get("total_currency")
    price = _fmt_money(car.get("total_amount"), currency)
    if car.get("rental_days") and car.get("daily_rate"):
        breakdown = f"{car['rental_days']} days × {_fmt_money(car['daily_rate'], currency)}"
        if car.get("taxes_amount"):
            breakdown += f" + {_fmt_money(car['taxes_amount'], currency)} taxes"
        price = f"{breakdown} = {price}"
    dates = (
        f"{_fmt_date(car['pickup_date'])} → {_fmt_date(car['dropoff_date'])} · "
        if car.get("pickup_date") and car.get("dropoff_date")
        else ""
    )
    return [f"**Rental car** · {car.get('vehicle')}, {car.get('vendor')}", f"- {dates}{price}"]


_CARD_DOMAINS = (
    ("flights", "selected_flight_id", "id", _flight_lines, "Flight"),
    ("stays", "selected_stay_id", "search_result_id", _stay_lines, "Hotel"),
    ("cars", "selected_car_id", "rate_id", _car_lines, "Rental car"),
)


def format_itinerary_for_review(itinerary: dict, research_results: dict) -> str:
    """Pure/deterministic: the compact markdown card shown to the traveler for approval."""
    blocks = []
    for domain, selection_key, id_field, render, label in _CARD_DOMAINS:
        if domain not in research_results:
            continue  # not requested
        item = _find(research_results, domain, id_field, itinerary.get(selection_key))
        if item is None:
            blocks.append(f"**{label}** · no option available (search failed or found nothing)")
        else:
            blocks.append("\n".join(render(item)))

    parts = blocks + [f"**Total: {itinerary.get('total_price', 'n/a')}**"]
    for warning in itinerary.get("warnings") or []:
        parts.append(f"⚠️ {warning}")
    if itinerary.get("summary"):
        parts.append(itinerary["summary"])
    parts.append("Reply **approve** to book it, tell me what you'd like **changed**, or **decline**.")
    return "\n\n".join(parts)
