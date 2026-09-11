from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVERS_DIR = REPO_ROOT / "mcp-servers"

# Hard restriction, not just a prompt instruction: the Researcher must never be able
# to call a book_*/cancel_*/get_*_booking tool, even if an MCP server happens to
# expose one. Only search-and-reprice tools are allowed through.
ALLOWED_TOOL_NAMES = {
    "search_flights",
    "get_offer",
    "search_stays",
    "get_stay_rate",
    "search_cars",
}


def _stdio_connection(server_dir: str) -> dict:
    server_path = MCP_SERVERS_DIR / server_dir
    return {
        "transport": "stdio",
        "command": str(server_path / ".venv" / "bin" / "python3"),
        "args": [str(server_path / "server.py")],
    }


async def load_researcher_tools() -> list:
    client = MultiServerMCPClient(
        {
            "flights": _stdio_connection("flights"),
            "stays": _stdio_connection("stays"),
            "cars": _stdio_connection("cars"),
        }
    )
    all_tools = await client.get_tools()
    allowed = [t for t in all_tools if t.name in ALLOWED_TOOL_NAMES]

    found_names = {t.name for t in allowed}
    missing = ALLOWED_TOOL_NAMES - found_names
    if missing:
        raise RuntimeError(f"Expected MCP tools not found: {missing}")

    return allowed
