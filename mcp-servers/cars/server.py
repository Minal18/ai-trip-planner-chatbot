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

# Cars access is currently gated on Duffel's side (403, account not yet approved).
# This lets development/testing proceed against realistic fake data in the meantime —
# scoped to search only, since that's the only tool Researcher currently calls.
# Swap back to real calls by removing/unsetting the env var, no code change needed.
MOCK_MODE = os.environ.get("DUFFEL_MOCK_MODE", "false").lower() == "true"

mcp = MCPServer("cars")


def _mock_cars_search_response(payload: dict) -> dict:
    pickup_address = f"Near {payload['data']['pickup_location']['geographic_coordinates']}"
    dropoff_address = f"Near {payload['data']['dropoff_location']['geographic_coordinates']}"
    vehicles = [
        ("Economy", "Rentacar Co.", "38.00"),
        ("Compact SUV", "DriveNow", "62.50"),
        ("Full-size", "Rentacar Co.", "79.00"),
    ]
    return {
        "data": {
            "rates": [
                {
                    "id": f"rat_mock_{i}",
                    "vehicle": {"name": name},
                    "vendor": {"name": vendor},
                    "total_amount": amount,
                    "total_currency": "USD",
                    "pickup_location": {"address": pickup_address},
                    "dropoff_location": {"address": dropoff_address},
                }
                for i, (name, vendor, amount) in enumerate(vehicles)
            ]
        }
    }


async def _request(method: str, path: str, **kwargs) -> dict:
    if MOCK_MODE and method == "POST" and path == "/cars/search":
        return _mock_cars_search_response(kwargs.get("json", {}))

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(method, f"{DUFFEL_API}{path}", headers=HEADERS, **kwargs)
    if response.status_code >= 400:
        try:
            errors = response.json().get("errors", response.text)
        except ValueError:
            errors = response.text
        return {"error": errors, "status_code": response.status_code}
    return response.json()


def _trim_rate(rate: dict) -> dict:
    return {
        "rate_id": rate["id"],
        "vehicle": rate.get("vehicle", {}).get("name"),
        "vendor": rate.get("vendor", {}).get("name"),
        "total_amount": rate.get("total_amount"),
        "total_currency": rate.get("total_currency"),
        "pickup_location": rate.get("pickup_location", {}).get("address"),
        "dropoff_location": rate.get("dropoff_location", {}).get("address"),
    }


@mcp.tool()
async def search_cars(
    pickup_latitude: float,
    pickup_longitude: float,
    pickup_date: str,
    pickup_time: str,
    dropoff_latitude: float,
    dropoff_longitude: float,
    dropoff_date: str,
    dropoff_time: str,
    driver_age: int,
    driver_residence_country_code: str,
    radius_km: int = 1,
) -> dict:
    """Search rental car rates for a pickup/dropoff location and time window.

    pickup_date/dropoff_date: ISO date strings ("YYYY-MM-DD").
    pickup_time/dropoff_time: 24h "HH:MM" strings.
    driver_residence_country_code: 2-letter ISO country code (e.g. "US").
    """
    payload = {
        "data": {
            "pickup_date": pickup_date,
            "pickup_time": pickup_time,
            "dropoff_date": dropoff_date,
            "dropoff_time": dropoff_time,
            "pickup_location": {
                "radius": radius_km,
                "geographic_coordinates": {"latitude": pickup_latitude, "longitude": pickup_longitude},
            },
            "dropoff_location": {
                "radius": radius_km,
                "geographic_coordinates": {"latitude": dropoff_latitude, "longitude": dropoff_longitude},
            },
            "driver": {"age": driver_age, "residence_country_code": driver_residence_country_code},
        }
    }
    result = await _request("POST", "/cars/search", json=payload)
    if "error" in result:
        return result

    rates = result["data"].get("rates", result["data"].get("results", []))[:10]
    return {"rates": [_trim_rate(r) for r in rates]}


@mcp.tool()
async def book_car(
    rate_id: str,
    driver_given_name: str,
    driver_family_name: str,
    driver_date_of_birth: str,
    driver_email: str,
    driver_phone_number: str,
) -> dict:
    """Book a rental car rate, creating a booking. Test mode only — no real charge or reservation is made.

    driver_date_of_birth: ISO date string ("YYYY-MM-DD").
    driver_phone_number: E.164 format (e.g. "+14155550123").
    """
    quote_result = await _request("POST", "/cars/quotes", json={"data": {"rate_id": rate_id}})
    if "error" in quote_result:
        return quote_result
    quote_id = quote_result["data"]["id"]

    payload = {
        "data": {
            "quote_id": quote_id,
            "driver": [
                {
                    "given_name": driver_given_name,
                    "family_name": driver_family_name,
                    "date_of_birth": driver_date_of_birth,
                    "email": driver_email,
                    "phone_number": driver_phone_number,
                }
            ],
        }
    }
    result = await _request("POST", "/cars/bookings", json=payload)
    if "error" in result:
        return result

    booking = result["data"]
    return {
        "booking_id": booking["id"],
        "reference": booking.get("reference"),
        "confirmed_at": booking.get("confirmed_at"),
    }


@mcp.tool()
async def get_car_booking(booking_id: str) -> dict:
    """Fetch the current status of a previously created car booking."""
    result = await _request("GET", f"/cars/bookings/{booking_id}")
    if "error" in result:
        return result

    booking = result["data"]
    return {
        "booking_id": booking["id"],
        "reference": booking.get("reference"),
        "status": "cancelled" if booking.get("cancelled_at") else "confirmed",
    }


@mcp.tool()
async def cancel_car_booking(booking_id: str) -> dict:
    """Cancel a previously created car booking."""
    result = await _request("POST", f"/cars/bookings/{booking_id}/actions/cancel")
    if "error" in result:
        return result

    booking = result["data"]
    return {"booking_id": booking["id"], "status": "cancelled"}


if __name__ == "__main__":
    mcp.run()
