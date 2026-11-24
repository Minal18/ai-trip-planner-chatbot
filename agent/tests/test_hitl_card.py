from hitl.nodes import format_itinerary_for_review


def _research_results():
    return {
        "flights": {
            "status": "ok",
            "items": [
                {
                    "id": "off_1",
                    "airline": "British Airways",
                    "cabin_class": "business",
                    "total_amount": "3890.71",
                    "total_currency": "USD",
                    "slices": [
                        {
                            "origin": "SEA",
                            "destination": "BOM",
                            "departing_at": "2026-11-26T19:21:00",
                            "arriving_at": "2026-11-28T02:02:00",
                            "stops": 1,
                            "segments": [
                                {"flight_number": "BA48", "origin": "SEA", "destination": "LHR",
                                 "departing_at": "2026-11-26T19:21:00", "arriving_at": "2026-11-27T12:40:00"},
                                {"flight_number": "BA199", "origin": "LHR", "destination": "BOM",
                                 "departing_at": "2026-11-27T21:50:00", "arriving_at": "2026-11-28T02:02:00"},
                            ],
                        }
                    ],
                }
            ],
        },
        "stays": {
            "status": "ok",
            "items": [
                {"search_result_id": "srez_1", "accommodation_name": "The Regency", "rating": 4.8,
                 "cheapest_rate_total_amount": "1563.52", "cheapest_rate_currency": "USD",
                 "check_in_date": "2026-11-28", "check_out_date": "2026-12-02",
                 "nights": 4, "nightly_rate": "349.00", "taxes_amount": "167.52"}
            ],
        },
        "cars": {"status": "error", "error": "not enabled"},
    }


def _itinerary(**overrides):
    return {
        "selected_flight_id": "off_1",
        "selected_stay_id": "srez_1",
        "selected_car_id": None,
        "total_price": "USD 5,454.23",
        "warnings": [],
        "summary": "Business class and a luxury hotel, as requested.",
        **overrides,
    }


def test_card_shows_connection_legs_and_layover():
    card = format_itinerary_for_review(_itinerary(), _research_results())
    assert "British Airways · Business" in card
    assert "**SEA → BOM** · 1 stop · Nov 26 19:21 → Nov 28 02:02" in card
    assert "BA48 SEA Nov 26 19:21 → LHR Nov 27 12:40" in card
    assert "layover 9h 10m in LHR" in card
    assert "BA199 LHR Nov 27 21:50 → BOM Nov 28 02:02" in card


def test_card_shows_hotel_nightly_breakdown_total_summary_and_actions():
    card = format_itinerary_for_review(_itinerary(), _research_results())
    assert "4 nights × USD 349.00 + USD 167.52 taxes = USD 1,563.52" in card
    assert "**Total: USD 5,454.23**" in card
    assert "Business class and a luxury hotel" in card
    assert card.rstrip().endswith("or **decline**.")


def test_card_flags_failed_domain_and_warnings_but_skips_unrequested_ones():
    results = _research_results()
    card = format_itinerary_for_review(_itinerary(warnings=["flight arrives 2026-11-28 but stay checks in 2026-11-26"]), results)
    assert "**Rental car** · no option available" in card
    assert "⚠️ flight arrives 2026-11-28" in card

    del results["cars"]
    assert "Rental car" not in format_itinerary_for_review(_itinerary(), results)


def test_card_omits_leg_list_for_nonstop_flights():
    results = _research_results()
    flight = results["flights"]["items"][0]
    flight["slices"][0]["stops"] = 0
    flight["slices"][0]["segments"] = flight["slices"][0]["segments"][:1]
    card = format_itinerary_for_review(_itinerary(), results)
    assert "nonstop" in card
    assert "layover" not in card
