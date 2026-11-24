"""Tests for the MCP server, called through a real MCP client in the same process."""
import asyncio

import pytest
from mcp import Client

from business_matcher_agent.mcp_server import server
from business_matcher_agent.tools import DB_PATH, search_business

needs_db = pytest.mark.skipif(not DB_PATH.exists(), reason="register.db not loaded")

FARWAY = "1562916"


def call(name: str, arguments: dict):
    """Call one tool through an MCP client and return the raw MCP result."""
    async def run():
        async with Client(server) as client:
            return await client.call_tool(name, arguments)
    return asyncio.run(run())


def list_tools():
    async def run():
        async with Client(server) as client:
            return (await client.list_tools()).tools
    return asyncio.run(run())


# --- what the server offers -----------------------------------------------------

def test_offers_exactly_the_three_tools():
    assert {t.name for t in list_tools()} == {"search_business", "get_business", "normalize_address"}


def test_every_tool_is_marked_read_only():
    for tool in list_tools():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.open_world_hint is False


def test_normalize_address_takes_only_an_address():
    tool = next(t for t in list_tools() if t.name == "normalize_address")
    assert set(tool.input_schema["properties"]) == {"address"}


# --- results match the plain functions ------------------------------------------

@needs_db
def test_search_gives_the_same_results_as_the_function():
    result = call("search_business", {"name": "Farway Marena", "limit": 5})
    assert not result.is_error
    via_mcp = [c["dos_id"] for c in result.structured_content["result"]]
    direct = [c["dos_id"] for c in search_business("Farway Marena", limit=5)]
    assert via_mcp == direct
    assert via_mcp[0] == FARWAY


@needs_db
def test_get_business_found_and_not_found():
    found = call("get_business", {"dos_id": FARWAY}).structured_content
    assert found["found"] is True
    assert found["company"]["Current Entity Name"] == "FARWAY MARINA INC."

    missing = call("get_business", {"dos_id": "999999999"}).structured_content
    assert missing == {"found": False, "dos_id": "999999999", "company": None}


def test_normalize_address_gives_the_standard_parts():
    result = call("normalize_address", {"address": "1790 Bay Boulevard, Suite 2, Atlantic Beach NY 11509"})
    assert result.structured_content == {
        "standard": "1790 BAY BLVD, 11509", "street_number": "1790",
        "street_name": "BAY BLVD", "zip": "11509",
    }


# --- bad input is rejected cleanly, not crashed on --------------------------------

@pytest.mark.parametrize("name, arguments", [
    ("get_business", {"dos_id": "1562916; DROP TABLE companies"}),
    ("get_business", {"dos_id": ""}),
    ("search_business", {"name": ""}),
    ("search_business", {"name": "x" * 201}),
    ("search_business", {"name": "Farway", "limit": 50}),
    ("search_business", {"name": "Farway", "street": "x" * 201}),
    ("normalize_address", {"address": "x" * 201}),
])
def test_bad_input_is_an_error_result(name, arguments):
    result = call(name, arguments)
    assert result.is_error
    assert "validation error" in result.content[0].text
