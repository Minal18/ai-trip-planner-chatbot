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

mcp = MCPServer("flights")


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


def _trim_offer(offer: dict) -> dict:
    return {
        "id": offer["id"],
        "total_amount": offer["total_amount"],
        "total_currency": offer["total_currency"],
        "airline": offer["owner"]["name"],
        "expires_at": offer.get("expires_at"),
        "slices": [
            {
                "origin": s["origin"]["iata_code"],
                "destination": s["destination"]["iata_code"],
                "departing_at": s["segments"][0]["departing_at"],
                "arriving_at": s["segments"][-1]["arriving_at"],
                "duration": s.get("duration"),
            }
            for s in offer["slices"]
        ],
    }


@mcp.tool()
async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    adults: int = 1,
) -> dict:
    """Search flight offers between two IATA airport codes.

    origin/destination: 3-letter IATA airport codes (e.g. "LHR", "JFK").
    departure_date/return_date: ISO date strings ("YYYY-MM-DD"). Omit return_date for a one-way search.
    """
    slices = [{"origin": origin, "destination": destination, "departure_date": departure_date}]
    if return_date:
        slices.append({"origin": destination, "destination": origin, "departure_date": return_date})

    payload = {
        "data": {
            "slices": slices,
            "passengers": [{"type": "adult"} for _ in range(adults)],
            "cabin_class": "economy",
        }
    }

    result = await _request("POST", "/air/offer_requests?return_offers=true", json=payload)
    if "error" in result:
        return result

    offers = result["data"]["offers"][:10]
    return {"offers": [_trim_offer(o) for o in offers]}


@mcp.tool()
async def get_offer(offer_id: str) -> dict:
    """Fetch full, current details and pricing for a specific offer (re-price before booking)."""
    result = await _request("GET", f"/air/offers/{offer_id}")
    if "error" in result:
        return result
    return _trim_offer(result["data"])


@mcp.tool()
async def book_flight(
    offer_id: str,
    passenger_given_name: str,
    passenger_family_name: str,
    passenger_email: str,
    passenger_born_on: str,
    passenger_gender: str,
    passenger_title: str,
    passenger_phone_number: str,
) -> dict:
    """Book a flight offer, creating an order. Test mode only — no real charge or ticket is issued.

    passenger_born_on: ISO date string ("YYYY-MM-DD").
    passenger_gender: "m" or "f" (per Duffel's passenger schema).
    passenger_title: e.g. "mr", "mrs", "ms".
    passenger_phone_number: E.164 format (e.g. "+14155550123").
    """
    # Duffel requires the order's passenger `id` to match the id Duffel assigned
    # when the offer was created — fetch it rather than inventing one.
    offer_result = await _request("GET", f"/air/offers/{offer_id}")
    if "error" in offer_result:
        return offer_result
    duffel_passenger_id = offer_result["data"]["passengers"][0]["id"]

    payload = {
        "data": {
            "selected_offers": [offer_id],
            "passengers": [
                {
                    "id": duffel_passenger_id,
                    "given_name": passenger_given_name,
                    "family_name": passenger_family_name,
                    "email": passenger_email,
                    "born_on": passenger_born_on,
                    "gender": passenger_gender,
                    "title": passenger_title,
                    "phone_number": passenger_phone_number,
                }
            ],
            "payments": [
                {
                    "type": "balance",
                    "amount": offer_result["data"]["total_amount"],
                    "currency": offer_result["data"]["total_currency"],
                }
            ],
        }
    }
    result = await _request("POST", "/air/orders", json=payload)
    if "error" in result:
        return result

    order = result["data"]
    return {
        "order_id": order["id"],
        "booking_reference": order["booking_reference"],
        "total_amount": order["total_amount"],
        "total_currency": order["total_currency"],
    }


@mcp.tool()
async def get_booking(order_id: str) -> dict:
    """Fetch the current status of a previously created order."""
    result = await _request("GET", f"/air/orders/{order_id}")
    if "error" in result:
        return result

    order = result["data"]
    return {
        "order_id": order["id"],
        "booking_reference": order["booking_reference"],
        "status": "cancelled" if order.get("cancelled_at") else "confirmed",
        "total_amount": order["total_amount"],
        "total_currency": order["total_currency"],
    }


@mcp.tool()
async def cancel_booking(order_id: str) -> dict:
    """Cancel a previously created order."""
    create_result = await _request("POST", "/air/order_cancellations", json={"data": {"order_id": order_id}})
    if "error" in create_result:
        return create_result

    cancellation_id = create_result["data"]["id"]
    confirm_result = await _request("POST", f"/air/order_cancellations/{cancellation_id}/actions/confirm")
    if "error" in confirm_result:
        return confirm_result

    return {"order_id": order_id, "status": "cancelled"}


if __name__ == "__main__":
    mcp.run()
