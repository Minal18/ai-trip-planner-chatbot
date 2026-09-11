import json

from langchain_core.messages import ToolMessage

TOOL_TO_DOMAIN = {
    "search_flights": "flights",
    "search_stays": "stays",
    "search_cars": "cars",
}

# Each server's search tool nests its list under a different key — not fully
# consistent across the three servers (built at different times), so this maps
# domain -> the key its trimmed tool output uses.
DOMAIN_LIST_KEY = {
    "flights": "offers",
    "stays": "results",
    "cars": "rates",
}

# Similarly, "price" isn't the same field name in every domain's trimmed output.
PRICE_FIELD_CANDIDATES = ("total_amount", "cheapest_rate_total_amount")


def _parse_tool_content(content) -> dict:
    if isinstance(content, list):
        # langchain-mcp-adapters wraps tool output as content blocks:
        # [{"type": "text", "text": "...json...", "id": "..."}, ...]
        text_parts = [
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "".join(text_parts) if text_parts else str(content)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {"error": content}
    if isinstance(content, dict):
        return content
    return {"error": str(content)}


def extract_results(messages: list) -> dict:
    """Walk the Researcher's tool-calling transcript and group results by domain.

    A domain is absent from the result entirely if its tool was never called
    (the request didn't need it) — distinct from being present with an error or
    an empty item list (the request needed it, but the search failed or found
    nothing).
    """
    research_results: dict = {}

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        domain = TOOL_TO_DOMAIN.get(message.name)
        if domain is None:
            continue  # a re-price tool like get_offer/get_stay_rate, not a search

        parsed = _parse_tool_content(message.content)
        existing = research_results.get(domain)

        if "error" in parsed:
            research_results[domain] = {"status": "error", "error": parsed["error"]}
            continue

        items = parsed.get(DOMAIN_LIST_KEY[domain], [])
        if existing and existing.get("status") == "ok":
            items = existing["items"] + items
        research_results[domain] = {"status": "ok", "items": items}

    return research_results


def _price_of(item: dict) -> float:
    for field in PRICE_FIELD_CANDIDATES:
        if item.get(field) is not None:
            try:
                return float(item[field])
            except (TypeError, ValueError):
                continue
    return float("inf")


def rank_and_normalize(research_results: dict, top_n: int = 5) -> dict:
    """Sort each domain's items by price ascending and trim to the top N. Pure/deterministic."""
    ranked = {}
    for domain, result in research_results.items():
        if result.get("status") != "ok":
            ranked[domain] = result
            continue
        sorted_items = sorted(result["items"], key=_price_of)
        ranked[domain] = {"status": "ok", "items": sorted_items[:top_n]}
    return ranked


def flag_insufficient(research_results: dict) -> list[str]:
    """Return the list of requested domains that failed or came back empty. Pure/deterministic."""
    insufficient = []
    for domain, result in research_results.items():
        if result.get("status") == "error":
            insufficient.append(domain)
        elif result.get("status") == "ok" and not result["items"]:
            insufficient.append(domain)
    return insufficient
