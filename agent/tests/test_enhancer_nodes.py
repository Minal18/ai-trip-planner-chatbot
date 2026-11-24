import pytest
from langchain_core.messages import AIMessage

from datetime import date

from enhancer.nodes import parse_response, roll_past_dates_forward


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


TODAY = date(2026, 11, 24)


def test_roll_past_dates_forward_moves_mis_yeared_trip_to_next_year():
    # The real bug: "jan 15th to jan 22nd" said on 2026-11-24 became 2026-01-15.
    request = {
        "flights": {"departure_date_earliest": "2026-01-15", "departure_date_latest": "2026-01-15", "return_date": "2026-01-22"},
        "stays": {"check_in_date": "2026-01-15", "check_out_date": "2026-01-22"},
        "cars": {"pickup_date": "2026-01-15", "dropoff_date": "2026-01-22", "pickup_time": "10:00"},
        "adults": 2,
    }
    rolled = roll_past_dates_forward(request, TODAY)
    assert rolled["flights"] == {"departure_date_earliest": "2027-01-15", "departure_date_latest": "2027-01-15", "return_date": "2027-01-22"}
    assert rolled["stays"] == {"check_in_date": "2027-01-15", "check_out_date": "2027-01-22"}
    assert rolled["cars"]["pickup_date"] == "2027-01-15" and rolled["cars"]["pickup_time"] == "10:00"
    assert rolled["adults"] == 2


def test_roll_past_dates_forward_keeps_future_and_today_dates():
    request = {"departure_date": "2026-11-24", "return_date": "2026-12-31"}
    assert roll_past_dates_forward(request, TODAY) == request


def test_roll_past_dates_forward_fixes_only_the_mis_yeared_return():
    request = {"departure_date": "2026-12-28", "return_date": "2026-01-03"}
    assert roll_past_dates_forward(request, TODAY) == {"departure_date": "2026-12-28", "return_date": "2027-01-03"}


def test_roll_past_dates_forward_leaves_non_date_fields_alone():
    request = {"origin": "2026-01-01", "notes": ["x"], "driver_date_of_birth": None}
    assert roll_past_dates_forward(request, TODAY) == request


def test_roll_past_dates_forward_never_touches_birth_dates():
    request = {"driver_date_of_birth": "1994-05-18", "date_of_birth": "1990-01-15", "born_on": "1988-06-02"}
    assert roll_past_dates_forward(request, TODAY) == request

