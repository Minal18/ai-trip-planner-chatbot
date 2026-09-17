from supervisor.nodes import decide_next_step


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


def test_routes_to_done_when_itinerary_status_decided():
    base_state = {
        "request": {"origin": "SEA"},
        "research_results": {"flights": {"status": "ok"}},
        "itinerary": {"summary": "..."},
    }
    for status in ("approved", "rejected", "edit_requested"):
        assert decide_next_step({**base_state, "itinerary_status": status}) == "done"
