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


# Hotel tier by rating. Duffel ratings are 1-5; thresholds chosen so each tier
# keeps a meaningful share of a typical result set.
STAY_TIER_RATING = {
    "budget": (0.0, 3.5),
    "midrange": (3.5, 4.3),
    "luxury": (4.3, 5.01),
}

# Car class -> keywords matched against the vehicle name (lower-cased).
# Order matters for "compact": a "Compact SUV" is an SUV, not a compact.
CAR_CLASS_KEYWORDS = {
    "economy": ("economy", "subcompact"),
    "compact": ("compact",),
    "midsize": ("midsize", "mid-size", "intermediate"),
    "fullsize": ("full-size", "fullsize", "full size", "standard"),
    "suv": ("suv",),
    "minivan": ("minivan", "van"),
    "premium": ("premium", "luxury", "convertible"),
}


def _max_stops(item: dict) -> int:
    return max((s.get("stops", 0) for s in item.get("slices", [])), default=0)


def _stay_matches_tier(item: dict, tier: str) -> bool:
    low, high = STAY_TIER_RATING[tier]
    rating = item.get("rating")
    return rating is not None and low <= float(rating) < high


def _car_matches_class(item: dict, car_class: str) -> bool:
    name = (item.get("vehicle") or "").lower()
    if car_class in ("compact", "economy") and "suv" in name:
        return False
    if car_class == "economy" and "compact" in name and "subcompact" not in name:
        return False
    return any(k in name for k in CAR_CLASS_KEYWORDS[car_class])


def _sort_key(domain: str, preferences: dict, preferred_departure_time: str):
    """Build the sort key for one domain. Preference matches always sort first, so
    they survive the top-N cut; within a group, cheapest first, except luxury
    hotels, where the best-rated comes first."""
    if domain == "flights":
        max_stops = preferences.get("flight_max_stops")

        def key(item):
            return (
                0 if max_stops is None or _max_stops(item) <= max_stops else 1,
                0 if preferred_departure_time not in TIME_BANDS
                or _matches_preferred_time(item, preferred_departure_time) else 1,
                _price_of(item),
            )

        return key

    if domain == "stays":
        tier = preferences.get("stay_tier", "any")
        if tier not in STAY_TIER_RATING:
            return _price_of

        def key(item):
            rating_first = -(float(item.get("rating") or 0)) if tier == "luxury" else 0
            return (0 if _stay_matches_tier(item, tier) else 1, rating_first, _price_of(item))

        return key

    if domain == "cars":
        car_class = preferences.get("car_class", "any")
        if car_class not in CAR_CLASS_KEYWORDS:
            return _price_of
        return lambda item: (0 if _car_matches_class(item, car_class) else 1, _price_of(item))

    return _price_of


def rank_and_normalize(
    research_results: dict,
    preferred_departure_time: str = "any",
    top_n: int = 5,
    preferences: dict | None = None,
) -> dict:
    """Sort each domain's items by how well they fit the traveler, then trim to the
    top N. Pure/deterministic.

    Preferences are a soft priority, not a hard filter: options matching the
    traveler's stated cabin/stops, departure time, hotel tier, or car class sort
    first, so they're never cut off by cheaper non-matching options, but if nothing
    matches, the traveler still sees the best alternatives instead of nothing. With
    no preferences stated, this is plain cheapest-first.
    """
    preferences = preferences or {}
    ranked = {}
    for domain, result in research_results.items():
        if result.get("status") != "ok":
            ranked[domain] = result
            continue

        sort_key = _sort_key(domain, preferences, preferred_departure_time)
        sorted_items = sorted(result["items"], key=sort_key)
        ranked[domain] = {"status": "ok", "items": sorted_items[:top_n]}
    return ranked


def flag_insufficient(research_results: dict, requested_domains: list[str] | None = None) -> list[str]:
    """Return the list of requested domains that failed, came back empty, or were
    never searched at all. Pure/deterministic.

    requested_domains (the Enhancer's explicit `domains` list) is the backstop for
    the Researcher LLM skipping a domain the traveler asked for: without it, a
    never-called tool is indistinguishable from "not requested" and would be
    silently dropped.
    """
    insufficient = [d for d in (requested_domains or []) if d not in research_results]
    for domain, result in research_results.items():
        if result.get("status") == "error":
            insufficient.append(domain)
        elif result.get("status") == "ok" and not result["items"]:
            insufficient.append(domain)
    return insufficient
