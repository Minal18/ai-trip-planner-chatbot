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

mcp = MCPServer("stays")


async def _request(method: str, path: str, **kwargs) -> dict:
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
