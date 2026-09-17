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


TIME_BANDS = ("morning", "afternoon", "evening", "night")


def _departure_hour(item: dict) -> int | None:
    """Flights-only: extract the departure hour from a trimmed offer's first slice."""
    try:
        departing_at = item["slices"][0]["departing_at"]
        return int(departing_at[11:13])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def _time_band(hour: int) -> str:
    if hour < 5:
        hour += 24  # fold 0:00-4:59 into the same band as 21:00-23:59
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def _matches_preferred_time(item: dict, preferred: str) -> bool:
    hour = _departure_hour(item)
    if hour is None:
        return False
    return _time_band(hour) == preferred


def rank_and_normalize(research_results: dict, preferred_departure_time: str = "any", top_n: int = 5) -> dict:
    """Sort each domain's items and trim to the top N. Pure/deterministic.

    For flights, if the traveler stated a preferred departure time band (not
    "any"), offers matching that band are prioritized first (still sorted by
    price within each group) — a soft priority, not a hard filter, so a much
    cheaper option outside the preferred band is never hidden entirely.
    """
    ranked = {}
    for domain, result in research_results.items():
        if result.get("status") != "ok":
            ranked[domain] = result
            continue

        if domain == "flights" and preferred_departure_time in TIME_BANDS:
            sort_key = lambda item: (  # noqa: E731
                0 if _matches_preferred_time(item, preferred_departure_time) else 1,
                _price_of(item),
            )
        else:
            sort_key = _price_of

        sorted_items = sorted(result["items"], key=sort_key)
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
