from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVERS_DIR = REPO_ROOT / "mcp-servers"

# Opposite restriction from Researcher: Booker only ever gets reprice/book/cancel
# tools — it must never be able to call search_* (no reason to search, and every
# tool call here has real, potentially irreversible consequences, so the tool set
# is kept as narrow as the job actually requires).
ALLOWED_TOOL_NAMES = {
    "get_offer",
    "book_flight",
    "cancel_booking",
    "get_stay_rate",
    "book_stay",
    "cancel_stay_booking",
    "book_car",
    "cancel_car_booking",
}


def _stdio_connection(server_dir: str) -> dict:
    server_path = MCP_SERVERS_DIR / server_dir
    return {
        "transport": "stdio",
        "command": str(server_path / ".venv" / "bin" / "python3"),
        "args": [str(server_path / "server.py")],
    }


async def load_booker_tools() -> dict:
    """Returns a dict keyed by tool name — Booker calls specific tools directly
    by name (deterministically, based on which itinerary fields are populated),
    not via an LLM deciding which to call."""
    client = MultiServerMCPClient(
        {
            "flights": _stdio_connection("flights"),
            "stays": _stdio_connection("stays"),
            "cars": _stdio_connection("cars"),
        }
    )
    all_tools = await client.get_tools()
    allowed = {t.name: t for t in all_tools if t.name in ALLOWED_TOOL_NAMES}

    missing = ALLOWED_TOOL_NAMES - set(allowed.keys())
    if missing:
        raise RuntimeError(f"Expected MCP tools not found: {missing}")

    return allowed
