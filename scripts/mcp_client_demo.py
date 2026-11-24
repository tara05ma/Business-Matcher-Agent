"""Start the MCP server, list its tools and call each one once.

Usage:  uv run python scripts/mcp_client_demo.py

This talks to the server exactly as the agent will: it launches the server as
a background process and sends requests over stdio.
"""
import asyncio
import json
import sys

from mcp import Client, StdioServerParameters

# Run the server with the same Python as this script, so it sees the same packages.
SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "business_matcher_agent.mcp_server"],
)

EXAMPLE_CALLS = [
    ("search_business", {
        "name": "Farway Marena",  # a typo on purpose
        "city": "Atlantic Beach, NY",
        "street": "1790 Bay Boulevard",
        "limit": 3,
    }),
    ("get_business", {"dos_id": "1562916"}),
    ("get_business", {"dos_id": "999999999"}),  # an ID that doesn't exist
    ("normalize_address", {"address": "1790 Bay Boulevard, Suite 2, Atlantic Beach NY 11509"}),
]


async def main() -> None:
    async with Client(SERVER) as client:
        print("Tools offered by the server:")
        for tool in (await client.list_tools()).tools:
            summary = (tool.description or "").splitlines()[0]
            print(f"  - {tool.name} (read-only: {tool.annotations.read_only_hint}): {summary}")

        for name, arguments in EXAMPLE_CALLS:
            print(f"\n>>> {name}({arguments})")
            result = await client.call_tool(name, arguments)
            if result.is_error:
                print("ERROR:", result.content[0].text)
            else:
                print(json.dumps(result.structured_content, indent=2)[:1500])


if __name__ == "__main__":
    asyncio.run(main())
