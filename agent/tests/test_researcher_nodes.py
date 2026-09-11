import json

from langchain_core.messages import AIMessage, ToolMessage

from researcher.nodes import extract_results, flag_insufficient, rank_and_normalize


def _tool_msg(name: str, content: dict) -> ToolMessage:
    return ToolMessage(content=json.dumps(content), name=name, tool_call_id=f"call_{name}")


def _tool_msg_content_blocks(name: str, content: dict) -> ToolMessage:
    # Reproduces the actual shape langchain-mcp-adapters hands back:
    # a list of content blocks, not a plain string.
    return ToolMessage(
        content=[{"type": "text", "text": json.dumps(content), "id": "lc_fake"}],
        name=name,
        tool_call_id=f"call_{name}",
    )


def test_extract_results_handles_mcp_adapter_content_block_shape():
    messages = [
        _tool_msg_content_blocks("search_flights", {"offers": [{"id": "off_1", "total_amount": "200.00"}]}),
    ]
    results = extract_results(messages)
    assert results["flights"]["status"] == "ok"
    assert results["flights"]["items"][0]["id"] == "off_1"


def test_extract_results_handles_mcp_adapter_content_block_error_shape():
    messages = [
        _tool_msg_content_blocks("search_stays", {"error": "not enabled for account", "status_code": 403}),
    ]
    results = extract_results(messages)
    assert results["stays"]["status"] == "error"
    assert results["stays"]["error"] == "not enabled for account"


def test_extract_results_only_includes_domains_actually_called():
    messages = [
        AIMessage(content="Let me search flights."),
        _tool_msg("search_flights", {"offers": [{"id": "off_1", "total_amount": "200.00"}]}),
    ]
    results = extract_results(messages)
    assert set(results.keys()) == {"flights"}
    assert results["flights"]["status"] == "ok"


def test_extract_results_marks_error_domain():
    messages = [
        _tool_msg("search_stays", {"error": "This feature is not enabled for your account.", "status_code": 403}),
    ]
    results = extract_results(messages)
    assert results["stays"]["status"] == "error"
    assert "not enabled" in results["stays"]["error"]


def test_extract_results_aggregates_multiple_calls_to_same_domain():
    messages = [
        _tool_msg("search_flights", {"offers": [{"id": "off_1", "total_amount": "200.00"}]}),
        _tool_msg("search_flights", {"offers": [{"id": "off_2", "total_amount": "150.00"}]}),
    ]
    results = extract_results(messages)
    assert len(results["flights"]["items"]) == 2


def test_extract_results_ignores_reprice_tools():
    messages = [_tool_msg("get_offer", {"id": "off_1", "total_amount": "200.00"})]
    results = extract_results(messages)
    assert results == {}


def test_rank_and_normalize_sorts_by_price_ascending_and_trims():
    research_results = {
        "flights": {
            "status": "ok",
            "items": [
                {"id": "off_1", "total_amount": "300.00"},
                {"id": "off_2", "total_amount": "150.00"},
                {"id": "off_3", "total_amount": "220.00"},
            ],
        }
    }
    ranked = rank_and_normalize(research_results, top_n=2)
    ids = [item["id"] for item in ranked["flights"]["items"]]
    assert ids == ["off_2", "off_3"]


def test_rank_and_normalize_handles_stays_alternate_price_field():
    research_results = {
        "stays": {
            "status": "ok",
            "items": [
                {"search_result_id": "sr_1", "cheapest_rate_total_amount": "500.00"},
                {"search_result_id": "sr_2", "cheapest_rate_total_amount": "300.00"},
            ],
        }
    }
    ranked = rank_and_normalize(research_results)
    assert ranked["stays"]["items"][0]["search_result_id"] == "sr_2"


def test_rank_and_normalize_leaves_error_domains_untouched():
    research_results = {"cars": {"status": "error", "error": "not enabled"}}
    assert rank_and_normalize(research_results) == research_results


def test_flag_insufficient_flags_errors_and_empty_results_only():
    research_results = {
        "flights": {"status": "ok", "items": [{"id": "off_1"}]},
        "stays": {"status": "error", "error": "not enabled"},
        "cars": {"status": "ok", "items": []},
    }
    assert set(flag_insufficient(research_results)) == {"stays", "cars"}


def test_flag_insufficient_ignores_domains_never_requested():
    research_results = {"flights": {"status": "ok", "items": [{"id": "off_1"}]}}
    assert flag_insufficient(research_results) == []
