EDIT_CLASSIFICATION_PROMPT = """\
A traveler was shown a proposed itinerary and asked for changes. Your job is to
decide which part of the system needs to handle their feedback:

- NeedsEnhancer: the feedback changes or adds a core trip detail that was already
  settled — a different origin city, a different destination, adding/removing a
  whole domain (e.g. "actually I also want a rental car" when none was searched
  for), or anything that needs clarifying questions to pin down (e.g. "let's try
  a different origin" without saying which one).
- NeedsResearcher: the feedback needs a genuinely new search — different dates,
  a different price range, a filter that wasn't searched for before — but the
  core trip details (origin, destination, travelers) are still valid as-is. If
  you pick this, you must also provide the full updated request, with whatever
  changed applied on top of the current request's fields.
- NeedsPlanner: the feedback can be satisfied by picking differently among
  results already gathered — e.g. "pick the cheaper flight," "I'd rather the
  earlier one," "use the other hotel instead." No new search needed.

You'll be given the traveler's feedback, the current request, and the research
results already gathered. Call exactly one of the three tools.
"""
