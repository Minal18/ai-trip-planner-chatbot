from pydantic import BaseModel, Field

from booker.nodes import failed_domains

# Booker reports flight/stay/car; the request's `domains` list says flights/stays/cars.
BOOKING_TO_REQUEST_DOMAIN = {"flight": "flights", "stay": "stays", "car": "cars"}


def decide_next_step(state: dict) -> str:
    """Pure/deterministic router — no LLM needed for these transitions, since each
    one is just checking which fields are still empty, with no ambiguity to
    resolve. (Classifying edit feedback is the one exception — see classify_edit_feedback.)
    """
    if state.get("request") is None:
        return "enhancer"
    if state.get("research_results") is None:
        return "researcher"
    if state.get("itinerary") is None:
        return "planner"
    if state.get("itinerary_status") is None:
        return "human_review"
    if state.get("itinerary_status") == "edit_requested":
        return "classify_edit_feedback"
    if state.get("itinerary_status") == "approved" and state.get("booking_result") is None:
        return "booker"
    if (
        state.get("booking_result")
        and failed_domains(state["booking_result"].get("booking_results"))
        and not state.get("retry_declined")
    ):
        return "offer_retry"
    return "done"  # rejected, approved-and-booked, or a failed piece the traveler chose to leave


class NeedsEnhancer(BaseModel):
    """The edit feedback changes or adds a core trip detail that needs clarifying
    questions to pin down — a different origin/destination, adding a whole domain
    that wasn't searched before, or anything too vague to act on directly (e.g.
    "let's try a different origin" without saying which one)."""


class NeedsResearcher(BaseModel):
    """The edit feedback needs a genuinely new search — different dates, a filter
    that wasn't searched for before — but core trip details are still valid."""

    updated_request: dict = Field(
        description="The full updated request dict: the current request's fields, with whatever the feedback changed applied on top."
    )


class NeedsPlanner(BaseModel):
    """The edit feedback can be satisfied by picking differently among results
    already gathered — e.g. "pick the cheaper flight," "use the other hotel
    instead." No new search needed."""


def parse_edit_classification(response) -> dict:
    """Pure/deterministic: turn the classification LLM's forced tool call into a
    state update. Clearing the relevant fields back to None is what makes the
    existing deterministic router rules (in decide_next_step) naturally cascade
    back to the right agent — no separate destination-routing needed here.
    """
    if not response.tool_calls:
        raise ValueError("Edit classification response contained no tool call — model did not follow instructions.")
    if len(response.tool_calls) != 1:
        raise ValueError(
            f"Expected exactly one tool call from edit classification, got {len(response.tool_calls)}: "
            f"{[c['name'] for c in response.tool_calls]}"
        )

    call = response.tool_calls[0]
    if call["name"] == "NeedsEnhancer":
        return {
            "request": None,
            "research_results": None,
            "itinerary": None,
            "itinerary_status": None,
            "edit_feedback": None,
        }
    elif call["name"] == "NeedsResearcher":
        return {
            "request": call["args"]["updated_request"],
            "research_results": None,
            "itinerary": None,
            "itinerary_status": None,
            "edit_feedback": None,
        }
    elif call["name"] == "NeedsPlanner":
        # request/research_results/edit_feedback stay as-is — Planner reads
        # edit_feedback directly and clears it itself once consumed.
        return {"itinerary": None, "itinerary_status": None}
    else:
        raise ValueError(f"Unexpected tool call from edit classification: {call['name']}")


class RetryFailedBookings(BaseModel):
    """The traveler wants to try again for the part(s) that didn't book (e.g. "yes",
    "retry", "search again", "try another flight")."""


class KeepAsIs(BaseModel):
    """The traveler doesn't want to retry the failed part(s) — keep what's confirmed
    and stop (e.g. "no", "leave it", "I'll book the flight myself")."""


def confirmed_bookings(state: dict) -> dict:
    """Pure: every booking confirmed so far — from earlier attempts plus the latest one."""
    latest = ((state.get("booking_result") or {}).get("booking_results")) or {}
    return {
        **(state.get("confirmed_bookings") or {}),
        **{d: r for d, r in latest.items() if "error" not in r},
    }


def parse_retry_decision(response, state: dict) -> dict:
    """Pure/deterministic: turn the retry classifier's forced tool call into a state
    update.

    Retry uses the same reset-and-cascade pattern as parse_edit_classification:
    clear research_results/itinerary/itinerary_status/booking_result back to None
    so decide_next_step walks Researcher -> Planner -> review -> Booker again — a
    fresh search, since a provider's "no longer available" means the old results
    are stale and retrying the same offer id can only fail again. The request is
    narrowed to just the failed domains. Deliberately carried across the reset:
    what already booked (confirmed_bookings — never cancelled, never rebooked; see
    docs/architecture.md §7.6) and the passenger details (not asked for twice).
    """
    if not response.tool_calls or len(response.tool_calls) != 1:
        raise ValueError(f"Expected exactly one retry-decision tool call, got {len(response.tool_calls or [])}")
    call = response.tool_calls[0]
    confirmed = confirmed_bookings(state)

    if call["name"] == "KeepAsIs":
        return {"retry_declined": True, "confirmed_bookings": confirmed}
    if call["name"] != "RetryFailedBookings":
        raise ValueError(f"Unexpected tool call: {call['name']}")

    failed = failed_domains(state["booking_result"]["booking_results"])
    return {
        "request": {**state["request"], "domains": [BOOKING_TO_REQUEST_DOMAIN[d] for d in failed]},
        "research_results": None,
        "insufficient_domains": None,
        "itinerary": None,
        "itinerary_status": None,
        "edit_feedback": None,
        "booking_result": None,
        "confirmed_bookings": confirmed,
        "passenger": state["booking_result"].get("passenger"),
    }
