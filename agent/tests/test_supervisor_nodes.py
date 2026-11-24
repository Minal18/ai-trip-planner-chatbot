import pytest
from langchain_core.messages import AIMessage

from supervisor.nodes import (
    TRIP_SLOTS,
    confirmed_bookings,
    decide_next_step,
    parse_edit_classification,
    parse_retry_decision,
    trip_reset,
)


def test_routes_to_enhancer_when_no_request_yet():
    assert decide_next_step({"request": None, "research_results": None}) == "enhancer"


def test_routes_to_enhancer_when_request_key_missing_entirely():
    assert decide_next_step({}) == "enhancer"


def test_routes_to_researcher_when_request_present_but_no_research_yet():
    assert decide_next_step({"request": {"origin": "SEA"}, "research_results": None}) == "researcher"


def test_routes_to_planner_when_research_present_but_no_itinerary_yet():
    assert (
        decide_next_step(
            {"request": {"origin": "SEA"}, "research_results": {"flights": {"status": "ok"}}, "itinerary": None}
        )
        == "planner"
    )


def test_routes_to_human_review_when_itinerary_present_but_no_decision_yet():
    assert (
        decide_next_step(
            {
                "request": {"origin": "SEA"},
                "research_results": {"flights": {"status": "ok"}},
                "itinerary": {"summary": "..."},
                "itinerary_status": None,
            }
        )
        == "human_review"
    )


def test_routes_to_done_when_rejected():
    base_state = {
        "request": {"origin": "SEA"},
        "research_results": {"flights": {"status": "ok"}},
        "itinerary": {"summary": "..."},
        "itinerary_status": "rejected",
    }
    assert decide_next_step(base_state) == "done"


def test_routes_to_booker_when_approved_but_not_booked_yet():
    base_state = {
        "request": {"origin": "SEA"},
        "research_results": {"flights": {"status": "ok"}},
        "itinerary": {"summary": "..."},
        "itinerary_status": "approved",
        "booking_result": None,
    }
    assert decide_next_step(base_state) == "booker"


def test_routes_to_done_when_approved_and_booked():
    base_state = {
        "request": {"origin": "SEA"},
        "research_results": {"flights": {"status": "ok"}},
        "itinerary": {"summary": "..."},
        "itinerary_status": "approved",
        "booking_result": {"final_message": "..."},
    }
    assert decide_next_step(base_state) == "done"


def test_routes_to_classify_edit_feedback_when_edit_requested():
    base_state = {
        "request": {"origin": "SEA"},
        "research_results": {"flights": {"status": "ok"}},
        "itinerary": {"summary": "..."},
        "itinerary_status": "edit_requested",
    }
    assert decide_next_step(base_state) == "classify_edit_feedback"


def _ai_message_with_tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call_1", "type": "tool_call"}])


def test_parse_edit_classification_needs_enhancer_clears_everything():
    result = parse_edit_classification(_ai_message_with_tool_call("NeedsEnhancer", {}))
    assert result == {
        "request": None,
        "research_results": None,
        "itinerary": None,
        "itinerary_status": None,
        "edit_feedback": None,
    }


def test_parse_edit_classification_needs_researcher_sets_updated_request():
    updated = {"origin": "PDX", "destination": "HNL"}
    result = parse_edit_classification(_ai_message_with_tool_call("NeedsResearcher", {"updated_request": updated}))
    assert result["request"] == updated
    assert result["research_results"] is None
    assert result["itinerary"] is None
    assert result["itinerary_status"] is None


def test_parse_edit_classification_needs_planner_only_clears_itinerary():
    result = parse_edit_classification(_ai_message_with_tool_call("NeedsPlanner", {}))
    assert result == {"itinerary": None, "itinerary_status": None}
    assert "request" not in result  # request/research_results/edit_feedback untouched


def test_parse_edit_classification_raises_on_unexpected_tool():
    import pytest

    with pytest.raises(ValueError):
        parse_edit_classification(_ai_message_with_tool_call("SomethingElse", {}))


FLIGHT_FAILED_STAY_OK = {
    "request": {"origin": "SEA", "destination": "JFK", "adults": 1, "domains": ["flights", "stays"]},
    "research_results": {"flights": {"status": "ok", "items": []}},
    "itinerary": {"summary": "..."},
    "itinerary_status": "approved",
    "booking_result": {
        "final_message": "...",
        "passenger": {"travelers": [{"given_name": "Jane"}], "email": "j@example.com", "phone_number": "+1"},
        "booking_results": {
            "flight": {"error": [{"code": "offer_no_longer_available", "message": "Please select another offer"}]},
            "stay": {"booking_id": "ord_1", "reference": "REF1"},
        },
    },
}


def _tool_call(name: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": "call_1", "type": "tool_call"}])


def test_routes_to_offer_retry_when_a_booking_failed():
    assert decide_next_step(FLIGHT_FAILED_STAY_OK) == "offer_retry"


def test_routes_to_done_when_traveler_declined_retry():
    assert decide_next_step({**FLIGHT_FAILED_STAY_OK, "retry_declined": True}) == "done"


def test_retry_resets_pipeline_slots_and_narrows_to_failed_domains():
    update = parse_retry_decision(_tool_call("RetryFailedBookings"), FLIGHT_FAILED_STAY_OK)
    for slot in ("research_results", "itinerary", "itinerary_status", "booking_result", "edit_feedback"):
        assert update[slot] is None
    assert update["request"]["domains"] == ["flights"]
    assert update["request"]["origin"] == "SEA"  # rest of the request kept
    # Carried across the reset: what booked, and who's travelling.
    assert update["confirmed_bookings"] == {"stay": {"booking_id": "ord_1", "reference": "REF1"}}
    assert update["passenger"]["email"] == "j@example.com"
    # And the router cascades back to a fresh search.
    assert decide_next_step({**FLIGHT_FAILED_STAY_OK, **update}) == "researcher"


def test_keep_as_is_records_decline_and_confirmed_bookings():
    update = parse_retry_decision(_tool_call("KeepAsIs"), FLIGHT_FAILED_STAY_OK)
    assert update["retry_declined"] is True
    assert "stay" in update["confirmed_bookings"]


def test_parse_retry_decision_raises_on_unexpected_tool():
    with pytest.raises(ValueError):
        parse_retry_decision(_tool_call("Approve"), FLIGHT_FAILED_STAY_OK)


def test_confirmed_bookings_merges_earlier_and_latest_successes():
    state = {
        "confirmed_bookings": {"stay": {"booking_id": "ord_1"}},
        "booking_result": {"booking_results": {"flight": {"order_id": "ord_2"}, "car": {"error": "x"}}},
    }
    assert set(confirmed_bookings(state)) == {"stay", "flight"}


def test_trip_reset_clears_every_slot_and_routes_to_enhancer():
    finished = {**FLIGHT_FAILED_STAY_OK, "retry_declined": True, "confirmed_bookings": {"stay": {}}}
    assert decide_next_step(finished) == "done"
    after = {**finished, **trip_reset()}
    assert all(after[slot] is None for slot in TRIP_SLOTS)
    assert decide_next_step(after) == "enhancer"


def test_trip_slots_cover_every_supervisor_state_field_except_messages():
    from supervisor.graph import SupervisorState

    assert set(TRIP_SLOTS) == set(SupervisorState.__annotations__) - {"messages"}
