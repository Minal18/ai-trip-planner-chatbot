from pydantic import BaseModel, Field


class AskQuestion(BaseModel):
    """Ask the traveler one clarifying question."""

    question: str = Field(description="A single, natural, conversational question.")


class RequestReady(BaseModel):
    """Declare that enough information has been gathered to proceed to search."""

    summary: str = Field(
        description="A plain-language summary of the understood trip request, to show the traveler before proceeding."
    )
    request: dict = Field(
        description=(
            "Structured fields, only including what's relevant to what the traveler asked for: "
            "origin, destination, departure_date_earliest, departure_date_latest (equal to each other "
            "for an exact date), return_date (optional), adults, check_in_date, check_out_date "
            "(if a stay is needed), pickup_location, pickup_date, dropoff_date (if a car is needed)."
        )
    )


def parse_response(response) -> dict:
    """Pure/deterministic: turn the Enhancer LLM's forced tool call into a state update."""
    if not response.tool_calls:
        raise ValueError("Enhancer response contained no tool call — model did not follow instructions.")

    call = response.tool_calls[0]
    if call["name"] == "RequestReady":
        return {
            "complete": True,
            "request": call["args"]["request"],
            "summary": call["args"]["summary"],
            "pending_question": None,
        }
    elif call["name"] == "AskQuestion":
        return {
            "complete": False,
            "pending_question": call["args"]["question"],
        }
    else:
        raise ValueError(f"Unexpected tool call from Enhancer: {call['name']}")
