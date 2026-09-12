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
            "request": {"origin": "SEA", "destination": "HNL", "departure_date_earliest": "2026-11-09"},
        },
    )
    result = parse_response(response)
    assert result["complete"] is True
    assert result["request"]["origin"] == "SEA"
    assert result["pending_question"] is None


def test_parse_response_raises_on_no_tool_call():
    response = AIMessage(content="I have a question but forgot to use the tool.")
    with pytest.raises(ValueError):
        parse_response(response)


def test_parse_response_raises_on_unexpected_tool_name():
    response = _ai_message_with_tool_call("SomeOtherTool", {})
    with pytest.raises(ValueError):
        parse_response(response)
