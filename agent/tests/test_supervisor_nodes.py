from langchain_core.messages import AIMessage

from supervisor.nodes import decide_next_step, parse_edit_classification


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
