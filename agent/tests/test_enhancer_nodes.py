import pytest
from langchain_core.messages import AIMessage

from enhancer.nodes import parse_response


def _ai_message_with_tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": "call_1", "type": "tool_call"}],
    )


def test_parse_response_ask_question():
    response = _ai_message_with_tool_call("AskQuestion", {"question": "Which airport are you flying from?"})
    result = parse_response(response)
    assert result["complete"] is False
    assert result["pending_question"] == "Which airport are you flying from?"


def test_parse_response_request_ready():
    response = _ai_message_with_tool_call(
        "RequestReady",
        {
            "summary": "Flight from Seattle to Honolulu, Nov 9-11, 1 adult.",
            "domains": ["flights"],
            "request": {"origin": "SEA", "destination": "HNL", "departure_date_earliest": "2026-11-09"},
        },
    )
    result = parse_response(response)
    assert result["complete"] is True
    assert result["request"]["origin"] == "SEA"
    assert result["request"]["domains"] == ["flights"]
    assert result["pending_question"] is None


def test_parse_response_request_ready_merges_all_domains_into_request():
    response = _ai_message_with_tool_call(
        "RequestReady",
        {
            "summary": "Flight, hotel and car for Delhi.",
            "domains": ["flights", "stays", "cars", "stays"],
            "request": {"origin": "SFO", "destination": "DEL", "check_in_date": "2026-12-10"},
        },
    )
    result = parse_response(response)
    assert result["request"]["domains"] == ["flights", "stays", "cars"]  # deduped, order kept
    assert result["request"]["destination"] == "DEL"


@pytest.mark.parametrize("domains", [None, [], ["flights", "trains"]])
def test_parse_response_request_ready_rejects_missing_or_unknown_domains(domains):
    args = {"summary": "...", "request": {"origin": "SFO"}}
    if domains is not None:
        args["domains"] = domains
    with pytest.raises(ValueError):
        parse_response(_ai_message_with_tool_call("RequestReady", args))


def test_parse_response_raises_on_no_tool_call():
    response = AIMessage(content="I have a question but forgot to use the tool.")
    with pytest.raises(ValueError):
        parse_response(response)


def test_parse_response_raises_on_unexpected_tool_name():
    response = _ai_message_with_tool_call("SomeOtherTool", {})
    with pytest.raises(ValueError):
        parse_response(response)


def test_parse_response_raises_on_multiple_tool_calls():
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "AskQuestion", "args": {"question": "..."}, "id": "call_1", "type": "tool_call"},
            {"name": "RequestReady", "args": {"summary": "...", "request": {}}, "id": "call_2", "type": "tool_call"},
        ],
    )
    with pytest.raises(ValueError):
        parse_response(response)


def test_parse_response_request_ready_fills_default_preferences_when_none_given():
    response = _ai_message_with_tool_call(
        "RequestReady", {"summary": "...", "domains": ["flights"], "request": {"origin": "SFO"}}
    )
    prefs = parse_response(response)["request"]["preferences"]
    assert prefs == {
        "flight_cabin": "economy",
        "flight_max_stops": None,
        "stay_tier": "any",
        "car_class": "any",
        "budget_note": None,
    }


def test_parse_response_request_ready_keeps_mixed_per_domain_preferences():
    response = _ai_message_with_tool_call(
        "RequestReady",
        {
            "summary": "...",
            "domains": ["flights", "stays", "cars"],
            "request": {"origin": "SEA", "destination": "BOM"},
            "preferences": {"flight_cabin": "business", "flight_max_stops": 1, "stay_tier": "luxury", "car_class": "economy"},
        },
    )
    prefs = parse_response(response)["request"]["preferences"]
    assert prefs["flight_cabin"] == "business"
    assert prefs["flight_max_stops"] == 1
    assert prefs["stay_tier"] == "luxury"
    assert prefs["car_class"] == "economy"


def test_parse_response_request_ready_rejects_unknown_preference_value():
    response = _ai_message_with_tool_call(
        "RequestReady",
        {"summary": "...", "domains": ["flights"], "request": {}, "preferences": {"flight_cabin": "super_luxe"}},
    )
    with pytest.raises(ValueError):
        parse_response(response)
