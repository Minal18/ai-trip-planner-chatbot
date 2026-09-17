import pytest
from langchain_core.messages import AIMessage

from planner.nodes import parse_response, validate_consistency


def _ai_message_with_tool_call(args: dict) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "ProposeItinerary", "args": args, "id": "call_1", "type": "tool_call"}],
    )


def test_parse_response_extracts_args():
    response = _ai_message_with_tool_call({"selected_flight_id": "off_1", "summary": "..."})
    result = parse_response(response)
    assert result["selected_flight_id"] == "off_1"


def test_parse_response_raises_on_no_tool_call():
    response = AIMessage(content="here's my pick: ...")
    with pytest.raises(ValueError):
        parse_response(response)


def test_parse_response_raises_on_wrong_tool_name():
    response = AIMessage(
        content="", tool_calls=[{"name": "SomethingElse", "args": {}, "id": "call_1", "type": "tool_call"}]
    )
    with pytest.raises(ValueError):
        parse_response(response)


FLIGHT = {
    "id": "off_1",
    "slices": [
        {"origin": "SEA", "destination": "HNL", "departing_at": "2026-11-15T10:00:00", "arriving_at": "2026-11-15T15:00:00"},
        {"origin": "HNL", "destination": "SEA", "departing_at": "2026-11-20T09:00:00", "arriving_at": "2026-11-20T17:00:00"},
    ],
}
STAY_ALIGNED = {"search_result_id": "sr_1", "check_in_date": "2026-11-15", "check_out_date": "2026-11-20"}
STAY_MISALIGNED = {"search_result_id": "sr_2", "check_in_date": "2026-11-15", "check_out_date": "2026-11-21"}


def _research_results(flight=None, stay=None, car=None):
    results = {}
    if flight:
        results["flights"] = {"status": "ok", "items": [flight]}
    if stay:
        results["stays"] = {"status": "ok", "items": [stay]}
    if car:
        results["cars"] = {"status": "ok", "items": [car]}
    return results


def test_validate_consistency_passes_when_dates_align():
    research_results = _research_results(flight=FLIGHT, stay=STAY_ALIGNED)
    itinerary = {"selected_flight_id": "off_1", "selected_stay_id": "sr_1"}
    assert validate_consistency(itinerary, research_results) == []


def test_validate_consistency_flags_checkout_mismatch():
    research_results = _research_results(flight=FLIGHT, stay=STAY_MISALIGNED)
    itinerary = {"selected_flight_id": "off_1", "selected_stay_id": "sr_2"}
    problems = validate_consistency(itinerary, research_results)
    assert len(problems) == 1
    assert "2026-11-20" in problems[0] and "2026-11-21" in problems[0]


def test_validate_consistency_flags_hallucinated_id():
    research_results = _research_results(flight=FLIGHT)
    itinerary = {"selected_flight_id": "off_does_not_exist"}
    problems = validate_consistency(itinerary, research_results)
    assert len(problems) == 1
    assert "off_does_not_exist" in problems[0]


def test_validate_consistency_ignores_domains_not_selected():
    research_results = _research_results(flight=FLIGHT, stay=STAY_ALIGNED)
    itinerary = {"selected_flight_id": "off_1", "selected_stay_id": None}
    assert validate_consistency(itinerary, research_results) == []


def test_validate_consistency_skips_date_check_for_one_way():
    one_way_flight = {"id": "off_2", "slices": [FLIGHT["slices"][0]]}
    research_results = _research_results(flight=one_way_flight, stay=STAY_MISALIGNED)
    itinerary = {"selected_flight_id": "off_2", "selected_stay_id": "sr_2"}
    # Only the outbound-arrival vs check-in comparison applies for one-way — and
    # those do align here — so no problems even though check_out_date is unrelated.
    assert validate_consistency(itinerary, research_results) == []
