from supervisor.nodes import decide_next_step


def test_routes_to_enhancer_when_no_request_yet():
    assert decide_next_step({"request": None, "research_results": None}) == "enhancer"


def test_routes_to_enhancer_when_request_key_missing_entirely():
    assert decide_next_step({}) == "enhancer"


def test_routes_to_researcher_when_request_present_but_no_research_yet():
    assert decide_next_step({"request": {"origin": "SEA"}, "research_results": None}) == "researcher"


def test_routes_to_done_when_both_present():
    assert (
        decide_next_step({"request": {"origin": "SEA"}, "research_results": {"flights": {"status": "ok"}}})
        == "done"
    )
