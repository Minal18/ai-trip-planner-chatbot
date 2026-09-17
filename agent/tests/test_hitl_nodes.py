import pytest
from langchain_core.messages import AIMessage

from hitl.nodes import parse_response


def _ai_message_with_tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call_1", "type": "tool_call"}])


def test_parse_response_approve():
    result = parse_response(_ai_message_with_tool_call("Approve", {}))
    assert result == {"itinerary_status": "approved", "edit_feedback": None}


def test_parse_response_request_edits():
    result = parse_response(_ai_message_with_tool_call("RequestEdits", {"feedback": "pick a cheaper hotel"}))
    assert result == {"itinerary_status": "edit_requested", "edit_feedback": "pick a cheaper hotel"}


def test_parse_response_reject():
    result = parse_response(_ai_message_with_tool_call("Reject", {}))
    assert result == {"itinerary_status": "rejected", "edit_feedback": None}


def test_parse_response_raises_on_no_tool_call():
    with pytest.raises(ValueError):
        parse_response(AIMessage(content="looks good!"))


def test_parse_response_raises_on_unexpected_tool_name():
    with pytest.raises(ValueError):
        parse_response(_ai_message_with_tool_call("SomethingElse", {}))
