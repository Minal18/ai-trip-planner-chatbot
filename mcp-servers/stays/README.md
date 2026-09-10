# Stays MCP Server

Wraps the Duffel Stays API as MCP tools: `search_stays`, `get_stay_rate`, `book_stay`, `get_stay_booking`, `cancel_stay_booking`.

## Status: blocked on account access

Duffel Stays is a separate product line from Flights and is **not enabled by default**, even in test mode. A live call currently returns:

```
403 Forbidden — "This feature is not enabled for your account. Please contact sales to get access: https://duffel.com/contact-us"
```

To unblock: contact Duffel via the link above and request Stays test-mode access for this account. Once granted, re-run the flow below to verify end-to-end (the way `mcp-servers/flights/server.py` was verified) — some field names in `server.py` were assembled from Duffel's docs rather than confirmed live, so expect the same kind of small fixes (missing required fields, payment shape) that came up while verifying the Flights server.

## Setup

Requires **Python 3.10+**.

```bash
cd mcp-servers/stays
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your Duffel test token
```

## Booking flow (once Stays access is granted)

1. `search_stays(latitude, longitude, check_in_date, check_out_date, ...)` — Duffel's test hotel lives at `latitude=-24.38, longitude=-128.32` (per Duffel's test-hotels guide); use a wide `radius_km` to make sure it's included.
2. `get_stay_rate(search_result_id)` — fetches all room rates for one search result (the initial search only returns the cheapest).
3. `book_stay(rate_id, ...)` — internally creates a quote (locks price/availability) then a booking from that quote.
4. `get_stay_booking(booking_id)` / `cancel_stay_booking(booking_id)`.

## Run standalone (MCP Inspector)

```bash
npx @modelcontextprotocol/inspector python server.py
```
