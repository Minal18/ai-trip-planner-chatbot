import os

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()

DUFFEL_API = "https://api.duffel.com"
DUFFEL_API_KEY = os.environ["DUFFEL_API_KEY"]
HEADERS = {
    "Authorization": f"Bearer {DUFFEL_API_KEY}",
    "Duffel-Version": "v2",
    "Content-Type": "application/json",
    "Accept-Encoding": "gzip",
}

# Stays access is currently gated on Duffel's side (403, account not yet approved).
# This lets development/testing proceed against realistic fake data in the meantime —
# covers search plus the full booking flow (rates, quote, booking, cancel), since
# Booker now exercises all of it, not just Researcher's search.
# Swap back to real calls by removing/unsetting the env var, no code change needed.
MOCK_MODE = os.environ.get("DUFFEL_MOCK_MODE", "false").lower() == "true"

mcp = MCPServer("stays")


def _mock_stays_search_response(payload: dict) -> dict:
    check_in = payload["data"]["check_in_date"]
    check_out = payload["data"]["check_out_date"]
    listings = [
        ("Seaside Budget Inn", 3.6, "142 Shoreline Ave", "129.00"),
        ("Traveler's Rest Motel", 3.4, "27 Airport Rd", "99.00"),
        ("Downtown Comfort Hotel", 4.1, "88 Market St", "189.50"),
        ("Palm Court Inn", 3.9, "310 Palm Ave", "159.00"),
        ("Harborview Suites", 4.6, "5 Harbor Blvd", "265.00"),
        ("The Grand Bayfront", 4.7, "1 Bayfront Plaza", "312.00"),
        ("Sunset Boutique Hotel", 4.3, "64 Sunset Blvd", "228.00"),
        ("Midtown Executive Suites", 4.0, "500 5th St", "199.00"),
        ("Riverside Garden Hotel", 4.4, "12 Riverside Walk", "241.50"),
        ("Central Plaza Hotel", 3.8, "77 Central Sq", "175.00"),
        ("The Regency", 4.8, "2 Regency Row", "349.00"),
        ("Budget Stay Express", 3.2, "900 Highway 1", "84.00"),
    ]
    return {
        "data": {
            "results": [
                {
                    "id": f"srez_mock_{i}",
                    "accommodation": {"name": name, "rating": rating, "location": {"address": address}},
                    "cheapest_rate_total_amount": amount,
                    "cheapest_rate_currency": "USD",
                    "check_in_date": check_in,
                    "check_out_date": check_out,
                }
                for i, (name, rating, address, amount) in enumerate(listings)
            ]
        }
    }


def _mock_fetch_all_rates_response() -> dict:
    return {
        "data": {
            "name": "Mock Accommodation",
            "rooms": [
                {
                    "name": "Standard Room",
                    "rates": [
                        {"id": "rat_mock_std_refundable", "total_amount": "149.00", "total_currency": "USD",
                         "payment_type": "pay_at_accommodation", "board_type": "room_only"},
                        {"id": "rat_mock_std_nonrefundable", "total_amount": "119.00", "total_currency": "USD",
                         "payment_type": "pay_now", "board_type": "room_only"},
                    ],
                },
                {
                    "name": "Deluxe Room, Breakfast Included",
                    "rates": [
                        {"id": "rat_mock_deluxe", "total_amount": "199.00", "total_currency": "USD",
                         "payment_type": "pay_at_accommodation", "board_type": "breakfast"},
                    ],
                },
            ],
        }
    }


def _mock_quote_response() -> dict:
    return {"data": {"id": "quo_mock_1", "total_amount": "149.00", "total_currency": "USD"}}


def _mock_booking_response() -> dict:
    return {"data": {"id": "ord_mock_1", "reference": "MOCKREF1", "status": "confirmed"}}


def _mock_get_booking_response() -> dict:
    return {
        "data": {
            "id": "ord_mock_1",
            "reference": "MOCKREF1",
            "status": "confirmed",
            "check_in_date": "2026-11-15",
            "check_out_date": "2026-11-20",
        }
    }


def _mock_cancel_response() -> dict:
    return {"data": {"id": "ord_mock_1", "status": "cancelled"}}


async def _request(method: str, path: str, **kwargs) -> dict:
    if MOCK_MODE:
        if method == "POST" and path == "/stays/search":
            return _mock_stays_search_response(kwargs.get("json", {}))
        if method == "POST" and path.startswith("/stays/search_results/") and path.endswith("/actions/fetch_all_rates"):
            return _mock_fetch_all_rates_response()
        if method == "POST" and path == "/stays/quotes":
            return _mock_quote_response()
        if method == "POST" and path == "/stays/bookings":
            return _mock_booking_response()
        if method == "POST" and path.startswith("/stays/bookings/") and path.endswith("/actions/cancel"):
            return _mock_cancel_response()
        if method == "GET" and path.startswith("/stays/bookings/"):
            return _mock_get_booking_response()

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(method, f"{DUFFEL_API}{path}", headers=HEADERS, **kwargs)
    if response.status_code >= 400:
        try:
            errors = response.json().get("errors", response.text)
        except ValueError:
            errors = response.text
        return {"error": errors, "status_code": response.status_code}
    return response.json()


def _trim_search_result(result: dict) -> dict:
    return {
        "search_result_id": result["id"],
        "accommodation_name": result["accommodation"]["name"],
        "rating": result["accommodation"].get("rating"),
        "location": result["accommodation"].get("location", {}).get("address"),
        "cheapest_rate_total_amount": result.get("cheapest_rate_total_amount"),
        "cheapest_rate_currency": result.get("cheapest_rate_currency"),
        "check_in_date": result["check_in_date"],
        "check_out_date": result["check_out_date"],
    }


def _trim_rate(rate: dict, room_name: str) -> dict:
    return {
        "rate_id": rate["id"],
        "room_name": room_name,
        "total_amount": rate["total_amount"],
        "total_currency": rate["total_currency"],
        "refundable": rate.get("payment_type") != "pay_now" or rate.get("cancellation_timeline") is not None,
        "board_type": rate.get("board_type"),
    }


@mcp.tool()
async def search_stays(
    latitude: float,
    longitude: float,
    check_in_date: str,
    check_out_date: str,
    adults: int = 1,
    rooms: int = 1,
    radius_km: int = 5,
) -> dict:
    """Search accommodations near a geographic point.

    latitude/longitude: decimal degrees of the search center point.
    check_in_date/check_out_date: ISO date strings ("YYYY-MM-DD").
    radius_km: search radius, 1-100km.
    """
    payload = {
        "data": {
            "location": {
                "radius": radius_km,
                "geographic_coordinates": {"latitude": latitude, "longitude": longitude},
            },
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "guests": [{"type": "adult"} for _ in range(adults)],
            "rooms": rooms,
        }
    }
    result = await _request("POST", "/stays/search", json=payload)
    if "error" in result:
        return result

    results = result["data"]["results"][:10]
    return {"results": [_trim_search_result(r) for r in results]}


@mcp.tool()
async def get_stay_rate(search_result_id: str) -> dict:
    """Fetch all available room rates for a search result (initial search only returns the cheapest)."""
    result = await _request("POST", f"/stays/search_results/{search_result_id}/actions/fetch_all_rates")
    if "error" in result:
        return result

    accommodation = result["data"]
    rates = []
    for room in accommodation.get("rooms", []):
        for rate in room.get("rates", []):
            rates.append(_trim_rate(rate, room.get("name", "")))
    return {"accommodation_name": accommodation.get("name"), "rates": rates}


@mcp.tool()
async def book_stay(
    rate_id: str,
    guest_given_name: str,
    guest_family_name: str,
    guest_email: str,
    guest_phone_number: str,
) -> dict:
    """Book a room rate, creating a stay booking. Test mode only — no real charge or reservation is made.

    guest_phone_number: E.164 format (e.g. "+14155550123").
    """
    quote_result = await _request("POST", "/stays/quotes", json={"data": {"rate_id": rate_id}})
    if "error" in quote_result:
        return quote_result
    quote = quote_result["data"]

    payload = {
        "data": {
            "quote_id": quote["id"],
            "email": guest_email,
            "phone_number": guest_phone_number,
            "guests": [{"given_name": guest_given_name, "family_name": guest_family_name}],
            "payment": {
                "type": "balance",
                "amount": quote["total_amount"],
                "currency": quote["total_currency"],
            },
        }
    }
    result = await _request("POST", "/stays/bookings", json=payload)
    if "error" in result:
        return result

    booking = result["data"]
    return {
        "booking_id": booking["id"],
        "reference": booking.get("reference"),
        "status": booking["status"],
        "total_amount": quote["total_amount"],
        "total_currency": quote["total_currency"],
    }


@mcp.tool()
async def get_stay_booking(booking_id: str) -> dict:
    """Fetch the current status of a previously created stay booking."""
    result = await _request("GET", f"/stays/bookings/{booking_id}")
    if "error" in result:
        return result

    booking = result["data"]
    return {
        "booking_id": booking["id"],
        "reference": booking.get("reference"),
        "status": booking["status"],
        "check_in_date": booking.get("check_in_date"),
        "check_out_date": booking.get("check_out_date"),
    }


@mcp.tool()
async def cancel_stay_booking(booking_id: str) -> dict:
    """Cancel a previously created stay booking."""
    result = await _request("POST", f"/stays/bookings/{booking_id}/actions/cancel")
    if "error" in result:
        return result

    booking = result["data"]
    return {"booking_id": booking["id"], "status": booking["status"]}


if __name__ == "__main__":
    mcp.run()
