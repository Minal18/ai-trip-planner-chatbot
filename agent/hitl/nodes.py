from pydantic import BaseModel, Field


class Approve(BaseModel):
    """The traveler approves the itinerary as presented and wants to proceed."""


class RequestEdits(BaseModel):
    """The traveler wants something changed before proceeding."""

    feedback: str = Field(description="The traveler's edit request, capturing their actual intent.")


class Reject(BaseModel):
    """The traveler does not want to proceed with this trip at all — not just a
    change to one part of it (that's RequestEdits), but declining the trip entirely."""


def parse_response(response) -> dict:
    """Pure/deterministic: turn the HITL classification LLM's forced tool call into a state update."""
    if not response.tool_calls:
        raise ValueError("HITL response contained no tool call — model did not follow instructions.")
    if len(response.tool_calls) != 1:
        raise ValueError(
            f"Expected exactly one tool call from HITL classification, got {len(response.tool_calls)}: "
            f"{[c['name'] for c in response.tool_calls]}"
        )

    call = response.tool_calls[0]
    if call["name"] == "Approve":
        return {"itinerary_status": "approved", "edit_feedback": None}
    elif call["name"] == "RequestEdits":
        return {"itinerary_status": "edit_requested", "edit_feedback": call["args"]["feedback"]}
    elif call["name"] == "Reject":
        return {"itinerary_status": "rejected", "edit_feedback": None}
    else:
        raise ValueError(f"Unexpected tool call from HITL classification: {call['name']}")
