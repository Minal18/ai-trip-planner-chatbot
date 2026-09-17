PASSENGER_EXTRACTION_PROMPT = """\
The traveler just replied with their booking details — full name, email, phone
number, date of birth, title, and gender — in free-form text. Extract these into
structured fields by calling the PassengerDetails tool.

- Split their name into given_name and family_name as best you can.
- phone_number must be in E.164 format (e.g. +14155550123) — infer a country
  code from context if they didn't give one explicitly and it's reasonably
  obvious, otherwise make your best reasonable guess (this is a best-effort
  extraction, not a place to fabricate wildly if something is genuinely absent).
- date_of_birth must be an ISO date (YYYY-MM-DD).
- title must be exactly one of "mr", "ms", "mrs", "miss", "dr" — use what the
  traveler actually stated, never guess it from their name.
- gender must be "m" or "f" — use what the traveler actually stated, never infer
  it from their name or title.
"""
