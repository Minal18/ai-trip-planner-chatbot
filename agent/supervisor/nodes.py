def decide_next_step(state: dict) -> str:
    """Pure/deterministic router. No LLM needed yet — with only Enhancer and
    Researcher to choose between, the decision is just checking which fields are
    still empty. Revisit once Planner/Booker introduce real judgment calls
    (e.g. does traveler feedback mean revise the request, or revise the itinerary?).
    """
    if state.get("request") is None:
        return "enhancer"
    if state.get("research_results") is None:
        return "researcher"
    return "done"
