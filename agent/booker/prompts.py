PASSENGER_EXTRACTION_PROMPT = """\
The traveler just replied with booking details for everyone on the trip — each
traveler's full name, date of birth, title, and gender, plus a contact email and
phone number — in free-form text. Extract these into structured fields by calling
the PassengerDetails tool.

- Add one entry to `travelers` per person they gave details for, lead traveler
  (the person writing, if they included themselves) first. Never invent a
  traveler or copy one person's details onto another to fill a gap.
- Split each name into given_name and family_name as best you can.
- date_of_birth must be an ISO date (YYYY-MM-DD).
- title must be exactly one of "mr", "ms", "mrs", "miss", "dr" — use what the
  traveler actually stated, never guess it from their name.
- gender must be "m" or "f" — use what the traveler actually stated, never infer
  it from their name or title.
- email and phone_number are one shared contact for the booking. If several were
  given, use the lead traveler's.
- phone_number must be in E.164 format (e.g. +14155550123) — infer a country
  code from context if they didn't give one explicitly and it's reasonably
  obvious, otherwise make your best reasonable guess (this is a best-effort
  extraction, not a place to fabricate wildly if something is genuinely absent).
"""
