SYSTEM_PROMPT = """\
You are classifying a traveler's response to a proposed trip itinerary. They were
shown a specific flight/hotel/car recommendation and asked to approve it, request
changes, or reject it entirely.

Read their reply and call exactly one of the three tools:
- Approve, if they're satisfied and want to proceed with booking.
- RequestEdits, if they want something changed — capture what they said as the
  feedback, cleaned up if needed but preserving their actual intent (e.g. a
  different flight, a cheaper hotel, a different origin city entirely).
- Reject, if they don't want to proceed with this trip at all — not just "change
  the hotel" or "try a different date" (those are edits), but genuinely declining
  the whole trip.
"""
