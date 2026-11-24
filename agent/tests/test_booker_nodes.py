import pytest
from langchain_core.messages import AIMessage

from booker.nodes import (
    booking_id_of,
    expected_traveler_count,
    flight_passengers,
    get_selected_items,
    parse_passenger_details,
    parse_tool_output,
    reference_of,
    traveler_count_problem,
)


def _ai_message_with_tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call_1", "type": "tool_call"}])


TWO_TRAVELERS = {
    "travelers": [
        {"given_name": "Jane", "family_name": "Doe", "date_of_birth": "1990-01-15", "title": "ms", "gender": "f"},
        {"given_name": "John", "family_name": "Doe", "date_of_birth": "1988-06-02", "title": "mr", "gender": "m"},
    ],
    "email": "jane@example.com",
    "phone_number": "+14155550123",
}


def test_parse_passenger_details_extracts_args():
    result = parse_passenger_details(_ai_message_with_tool_call("PassengerDetails", TWO_TRAVELERS))
    assert result == TWO_TRAVELERS


def test_parse_passenger_details_raises_on_no_tool_call():
    with pytest.raises(ValueError):
        parse_passenger_details(AIMessage(content="Jane Doe, jane@example.com"))


def test_parse_passenger_details_raises_on_wrong_tool():
    with pytest.raises(ValueError):
        parse_passenger_details(_ai_message_with_tool_call("SomethingElse", {}))


def test_get_selected_items_finds_each_domain():
    research_results = {
        "flights": {"status": "ok", "items": [{"id": "off_1", "total_amount": "100"}]},
        "stays": {"status": "ok", "items": [{"search_result_id": "sr_1", "cheapest_rate_total_amount": "50"}]},
        "cars": {"status": "ok", "items": [{"rate_id": "rat_1", "total_amount": "20"}]},
    }
    itinerary = {"selected_flight_id": "off_1", "selected_stay_id": "sr_1", "selected_car_id": "rat_1"}
    result = get_selected_items(itinerary, research_results)
    assert result["flight"]["id"] == "off_1"
    assert result["stay"]["search_result_id"] == "sr_1"
    assert result["car"]["rate_id"] == "rat_1"


def test_get_selected_items_none_for_unselected_domains():
    research_results = {"flights": {"status": "ok", "items": [{"id": "off_1"}]}}
    itinerary = {"selected_flight_id": "off_1", "selected_stay_id": None, "selected_car_id": None}
    result = get_selected_items(itinerary, research_results)
    assert result["stay"] is None
    assert result["car"] is None


def test_parse_tool_output_unwraps_content_blocks():
    content = [{"type": "text", "text": '{"total_amount": "100.00"}', "id": "lc_1"}]
    assert parse_tool_output(content) == {"total_amount": "100.00"}


def test_parse_tool_output_passes_through_plain_dict():
    assert parse_tool_output({"total_amount": "100.00"}) == {"total_amount": "100.00"}


def test_booking_id_of_flights_shape():
    assert booking_id_of({"order_id": "ord_1", "booking_reference": "ABC123"}) == "ord_1"


def test_booking_id_of_stays_cars_shape():
    assert booking_id_of({"booking_id": "ord_2", "reference": "XYZ789"}) == "ord_2"


def test_reference_of_flights_shape():
    assert reference_of({"order_id": "ord_1", "booking_reference": "ABC123"}) == "ABC123"


def test_reference_of_stays_cars_shape():
    assert reference_of({"booking_id": "ord_2", "reference": "XYZ789"}) == "XYZ789"


def test_expected_traveler_count_prefers_offer_passenger_count():
    assert expected_traveler_count({"adults": 1}, {"id": "off_1", "passenger_count": 2}) == 2


def test_expected_traveler_count_falls_back_to_request_adults():
    assert expected_traveler_count({"adults": 3}, None) == 3
    assert expected_traveler_count({"adults": "2"}, {"id": "off_1"}) == 2


def test_expected_traveler_count_defaults_to_one():
    assert expected_traveler_count(None, None) == 1
    assert expected_traveler_count({"adults": None}, None) == 1


def test_traveler_count_problem_none_when_matching():
    assert traveler_count_problem(TWO_TRAVELERS, 2) is None


def test_traveler_count_problem_flags_mismatch():
    one = {**TWO_TRAVELERS, "travelers": TWO_TRAVELERS["travelers"][:1]}
    problem = traveler_count_problem(one, 2)
    assert problem is not None and "2 traveler" in problem and "for 1" in problem


def test_flight_passengers_one_entry_per_traveler_with_shared_contact():
    result = flight_passengers(TWO_TRAVELERS)
    assert len(result) == 2
    assert result[0] == {
        "given_name": "Jane",
        "family_name": "Doe",
        "born_on": "1990-01-15",
        "gender": "f",
        "title": "ms",
        "email": "jane@example.com",
        "phone_number": "+14155550123",
    }
    assert result[1]["given_name"] == "John" and result[1]["email"] == "jane@example.com"
