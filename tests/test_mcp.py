import json

import anyio
import pytest
from mcp import Client

from backlinker.mcp_server import build
from backlinker.vaults import save_config


@pytest.fixture
def server(demo):
    save_config({"default": "demo", "vaults": {"demo": {"path": str(demo.root), "heading": "## Log"}}})
    return build()


def call(server, tool, **args):
    async def go():
        async with Client(server) as client:
            if tool is None:
                return [t.name for t in (await client.list_tools()).tools]
            res = await client.call_tool(tool, args)
            assert not res.is_error, res.content
            if res.structured_content:
                return res.structured_content.get("result", res.structured_content)
            return json.loads(res.content[0].text)
    return anyio.run(go)


def test_lists_tools(server):
    assert sorted(call(server, None)) == ["capture", "find_note", "preview_links", "undo_last"]


def test_preview_writes_nothing(server, demo):
    got = call(server, "preview_links", text="Maya and Sam")
    assert got["links"] == ["Maya Chen"] and got["ambiguous"][0]["text"] == "Sam"
    assert not list((demo.root / "Daily").glob("2026-10-07*"))


def test_capture_dry_run_then_real_then_undo(server, demo):
    dry = call(server, "capture", text="Jonas wants the deck", dry_run=True)
    assert dry["dry_run"] and "+++ Daily/" in dry["diff"]
    real = call(server, "capture", text="Jonas wants the deck fri", task=True, to=["Harbor"])
    assert real["due"] and "Projects/Harbor Launch.md" in real["files"]
    assert "[[Jonas Weber|Jonas]]" in (demo.root / "Projects/Harbor Launch.md").read_text()
    undone = call(server, "undo_last")
    assert undone["undone"].startswith("mcp: Jonas")
    assert "Jonas" not in (demo.root / "Projects/Harbor Launch.md").read_text()


def test_capture_into_another_day(server, demo):
    call(server, "capture", text="late note", day="2026-10-06")
    assert (demo.root / "Daily/2026-10-06.md").read_text().endswith("- late note\n")


def test_find_note(server):
    rows = call(server, "find_note", query="northwind")
    assert rows[0]["path"] == "Companies/Northwind Capital.md" and rows[0]["aliases"] == ["Northwind"]
    assert call(server, "find_note", query="zzzz") == []
