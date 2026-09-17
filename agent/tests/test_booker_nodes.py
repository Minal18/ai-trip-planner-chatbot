import pytest
from langchain_core.messages import AIMessage

from booker.nodes import (
    booking_id_of,
    get_selected_items,
    parse_passenger_details,
    parse_tool_output,
    price_changed_materially,
    reference_of,
)


def _ai_message_with_tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call_1", "type": "tool_call"}])


def test_parse_passenger_details_extracts_args():
    args = {
        "given_name": "Jane",
        "family_name": "Doe",
        "email": "jane@example.com",
        "phone_number": "+14155550123",
        "date_of_birth": "1990-01-15",
        "title": "ms",
        "gender": "f",
    }
    result = parse_passenger_details(_ai_message_with_tool_call("PassengerDetails", args))
    assert result == args


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


def test_price_changed_materially_small_change_not_flagged():
    assert price_changed_materially("100.00", "101.00") is False  # 1% change


def test_price_changed_materially_large_change_flagged():
    assert price_changed_materially("100.00", "110.00") is True  # 10% change


def test_price_changed_materially_exactly_at_threshold_not_flagged():
    assert price_changed_materially("100.00", "102.00") is False  # exactly 2%


def test_price_changed_materially_unparseable_defaults_to_changed():
    assert price_changed_materially("100.00", None) is True
    assert price_changed_materially(None, "100.00") is True


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
