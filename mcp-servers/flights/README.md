# Flights MCP Server

Wraps the Duffel Flights API as MCP tools: `search_flights`, `get_offer`, `book_flight`, `get_booking`, `cancel_booking`.

Requires **Python 3.10+** (the `mcp` SDK does not support 3.9).

## Setup

```bash
cd mcp-servers/flights
python3.10+ -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your Duffel test token
```

`DUFFEL_API_KEY` must be a **test-mode** token (`duffel_test_...`) from the Duffel dashboard (Developers → Access Tokens, in Test mode). Test mode is sandboxed against a fake airline ("Duffel Airways") — no real inventory or charges.

## Booking a flight

`book_flight` takes the `offer_id` and a `passengers` list with **one entry per traveler on the offer**. The offer was searched for a fixed number of `adults`, and the tool returns an error if the counts differ (Duffel rejects such an order). Each entry needs the fields Duffel requires for order creation: `given_name`, `family_name`, `email`, `born_on` (`YYYY-MM-DD`), `gender` (`m`/`f`), `title` (`mr`/`mrs`/`ms`), `phone_number` (E.164, e.g. `+14155550123`). The same email and phone can be repeated across passengers. Search and offer results include `passenger_count`. Payment is automatic: the tool pays with the offer's exact amount via the `balance` payment type against your Duffel test-mode balance.

## Run standalone (MCP Inspector)

```bash
npx @modelcontextprotocol/inspector python server.py
```

Opens a web UI to call each tool directly. Try `search_flights` with `origin=LHR`, `destination=JFK`, a near-future `departure_date`.

## Verified

Ran end-to-end against Duffel's test API: `search_flights` → `get_offer` → `book_flight` → `get_booking` (confirmed) → `cancel_booking` → `get_booking` (cancelled). All 5 tools work against real (sandboxed) Duffel responses.

## Wire into the LangGraph agent

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "flights": {
        "command": "python",
        "args": ["mcp-servers/flights/server.py"],
        "transport": "stdio",
    }
})
tools = await client.get_tools()
```
