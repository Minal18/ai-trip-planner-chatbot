def decide_next_step(state: dict) -> str:
    """Pure/deterministic router — no LLM needed for these transitions, since each
    one is just checking which fields are still empty, with no ambiguity to
    resolve. (Classifying edit feedback is the one exception — see classify_edit_feedback.)
    """
    if state.get("request") is None:
        return "enhancer"
    if state.get("research_results") is None:
        return "researcher"
    if state.get("itinerary") is None:
        return "planner"
    if state.get("itinerary_status") is None:
        return "human_review"
    # "edit_requested" temporarily also ends here — classify_edit_feedback (the
    # real routing for edits, back to Enhancer/Researcher/Planner) lands next.
    return "done"
