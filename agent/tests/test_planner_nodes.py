import pytest
from langchain_core.messages import AIMessage

from planner.nodes import check_dates, parse_response, validate_consistency


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
    assert "21 Nov" in problems[0] and "20 Nov" in problems[0]


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


def _flight(out_dep, out_arr, ret_dep=None, ret_arr=None):
    slices = [{"departing_at": out_dep, "arriving_at": out_arr}]
    if ret_dep:
        slices.append({"departing_at": ret_dep, "arriving_at": ret_arr})
    return {"id": "off_x", "slices": slices}


def _stay(check_in, check_out):
    return {"search_result_id": "sr_x", "check_in_date": check_in, "check_out_date": check_out}


def _car(pickup, dropoff):
    return {"rate_id": "rat_x", "pickup_date": pickup, "dropoff_date": dropoff}


SELECT_ALL = {"selected_flight_id": "off_x", "selected_stay_id": "sr_x", "selected_car_id": "rat_x"}

# The case from a real trace: SEA->JFK red-eye landing 03:19 the next day, return
# departing 23:13 on check-out day. Used to be rejected, forcing a 2.8x pricier flight.
RED_EYE = _flight("2026-12-25T18:34:00", "2026-12-26T03:19:00", "2026-12-31T23:13:00", "2027-01-01T01:58:00")


def test_red_eye_with_checkin_on_departure_day_is_aligned():
    rr = _research_results(flight=RED_EYE, stay=_stay("2026-12-25", "2026-12-31"))
    assert check_dates({"selected_flight_id": "off_x", "selected_stay_id": "sr_x"}, rr) == ([], [])


def test_red_eye_with_checkin_on_landing_day_is_aligned():
    rr = _research_results(flight=RED_EYE, stay=_stay("2026-12-26", "2026-12-31"))
    assert check_dates({"selected_flight_id": "off_x", "selected_stay_id": "sr_x"}, rr) == ([], [])


def test_stay_starting_after_landing_is_a_problem():
    same_day = _flight("2026-12-25T07:00:00", "2026-12-25T15:30:00", "2026-12-31T16:30:00", "2026-12-31T20:12:00")
    rr = _research_results(flight=same_day, stay=_stay("2026-12-26", "2026-12-31"))
    problems, _ = check_dates({"selected_flight_id": "off_x", "selected_stay_id": "sr_x"}, rr)
    assert len(problems) == 1 and "no room for your first 1 night" in problems[0]


def test_long_haul_two_days_checkin_on_departure_day_is_a_note_not_a_problem():
    # SEA -> DEL departing 25 Dec, landing 27 Dec 02:00 (crosses 2 days).
    long_haul = _flight("2026-12-25T21:00:00", "2026-12-27T02:00:00")
    rr = _research_results(flight=long_haul, stay=_stay("2026-12-25", "2027-01-02"))
    problems, notes = check_dates({"selected_flight_id": "off_x", "selected_stay_id": "sr_x"}, rr)
    assert problems == []
    assert len(notes) == 1 and "1 night before you arrive" in notes[0] and "2 days after departing" in notes[0]


def test_long_haul_afternoon_landing_needs_no_prior_night():
    long_haul = _flight("2026-12-25T21:00:00", "2026-12-27T14:00:00")
    rr = _research_results(flight=long_haul, stay=_stay("2026-12-27", "2027-01-02"))
    assert check_dates({"selected_flight_id": "off_x", "selected_stay_id": "sr_x"}, rr) == ([], [])


def test_early_morning_return_allows_checkout_the_day_before():
    early_return = _flight("2026-12-25T07:00:00", "2026-12-25T15:00:00", "2027-01-01T01:30:00", "2027-01-01T09:00:00")
    rr = _research_results(flight=early_return, stay=_stay("2026-12-25", "2026-12-31"), car=_car("2026-12-25", "2026-12-31"))
    assert check_dates(SELECT_ALL, rr) == ([], [])


def test_checkout_after_return_flight_is_a_problem():
    rr = _research_results(flight=RED_EYE, stay=_stay("2026-12-25", "2027-01-01"))
    problems, _ = check_dates({"selected_flight_id": "off_x", "selected_stay_id": "sr_x"}, rr)
    assert len(problems) == 1 and "after your return flight leaves 31 Dec" in problems[0]


def test_car_pickup_before_landing_is_a_problem():
    rr = _research_results(flight=RED_EYE, car=_car("2026-12-25", "2026-12-31"))
    problems, _ = check_dates({"selected_flight_id": "off_x", "selected_car_id": "rat_x"}, rr)
    assert len(problems) == 1 and "no-show" in problems[0] and "26 Dec" in problems[0]


def test_car_pickup_on_landing_day_is_aligned():
    rr = _research_results(flight=RED_EYE, car=_car("2026-12-26", "2026-12-31"))
    assert check_dates({"selected_flight_id": "off_x", "selected_car_id": "rat_x"}, rr) == ([], [])


def test_car_due_back_after_return_flight_is_a_problem():
    rr = _research_results(flight=RED_EYE, car=_car("2026-12-26", "2027-01-01"))
    problems, _ = check_dates({"selected_flight_id": "off_x", "selected_car_id": "rat_x"}, rr)
    assert len(problems) == 1 and "car is due back 1 Jan" in problems[0]


def test_car_pickup_days_after_landing_is_a_note():
    rr = _research_results(flight=RED_EYE, car=_car("2026-12-28", "2026-12-31"))
    problems, notes = check_dates({"selected_flight_id": "off_x", "selected_car_id": "rat_x"}, rr)
    assert problems == [] and len(notes) == 1 and "2 days after you land" in notes[0]


def test_validate_consistency_returns_only_blocking_problems():
    long_haul = _flight("2026-12-25T21:00:00", "2026-12-27T02:00:00")
    rr = _research_results(flight=long_haul, stay=_stay("2026-12-25", "2027-01-02"))
    assert validate_consistency({"selected_flight_id": "off_x", "selected_stay_id": "sr_x"}, rr) == []


def _results_for_total():
    return {
        "flights": {"status": "ok", "items": [{"id": "off_1", "total_amount": "890.71", "total_currency": "USD"}]},
        "stays": {"status": "ok", "items": [{"search_result_id": "srez_1", "cheapest_rate_total_amount": "577.92", "cheapest_rate_currency": "USD"}]},
        "cars": {"status": "ok", "items": [{"rate_id": "rat_1", "total_amount": "149.50", "total_currency": "EUR"}]},
    }


def test_compute_total_sums_selected_items_per_currency():
    from planner.nodes import compute_total

    itinerary = {"selected_flight_id": "off_1", "selected_stay_id": "srez_1", "selected_car_id": "rat_1"}
    assert compute_total(itinerary, _results_for_total()) == "USD 1,468.63 + EUR 149.50"


def test_compute_total_ignores_unselected_and_unknown_ids():
    from planner.nodes import compute_total

    itinerary = {"selected_flight_id": "off_1", "selected_stay_id": "does_not_exist", "selected_car_id": None}
    assert compute_total(itinerary, _results_for_total()) == "USD 890.71"
    assert compute_total({}, _results_for_total()) == "n/a"
