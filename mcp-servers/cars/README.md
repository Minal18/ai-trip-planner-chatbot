# Cars MCP Server

Wraps the Duffel Cars API as MCP tools: `search_cars`, `book_car`, `get_car_booking`, `cancel_car_booking`.

## Status: blocked on account access

Duffel Cars is a separate product line, gated the same way as Stays — even in test mode. A live call currently returns:

```
403 Forbidden — "This feature is not enabled for your account. Please contact sales to get access: https://duffel.com/contact-us"
```

Access has already been requested via https://duffel.com/contact-us (same request covers Stays). Once granted, re-run the flow below to verify end-to-end, the way `mcp-servers/flights/server.py` was verified.

Endpoints were confirmed empirically (`403` = recognized route, `404` = wrong path) against Duffel's real API — not just assumed from docs:
- `POST /cars/search`
- `POST /cars/quotes`
- `POST /cars/bookings`
- `GET /cars/bookings/{id}`
- `POST /cars/bookings/{id}/actions/cancel`

Request/response field names for `search_cars` and `book_car` are based on the example payloads in [Duffel's Cars getting-started guide](https://duffel.com/docs/guides/getting-started-with-cars) — the exact shape of a search response's rate list wasn't fully documented there, so `_trim_rate` in `server.py` may need small field-name fixes once we can actually see a live response.

## Setup

Requires **Python 3.10+**.

```bash
cd mcp-servers/cars
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your Duffel test token
```

## Booking flow (once Cars access is granted)

1. `search_cars(pickup_latitude, pickup_longitude, pickup_date, pickup_time, dropoff_latitude, dropoff_longitude, dropoff_date, dropoff_time, driver_age, driver_residence_country_code)` — returns a shortlist of rates.
2. `book_car(rate_id, ...)` — internally creates a quote (locks price/availability) then a booking from that quote, same pattern as `book_stay`.
3. `get_car_booking(booking_id)` / `cancel_car_booking(booking_id)`.

## Run standalone (MCP Inspector)

```bash
npx @modelcontextprotocol/inspector python server.py
```
