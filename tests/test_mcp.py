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
    assert sorted(call(server, None)) == ["add_to_dossier", "capture", "dossier", "find_note", "guest_list",
                                          "preview_links", "undo_last"]


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


def test_dossier_reads_without_writing_unless_asked(server, demo):
    got = call(server, "dossier", name="Maya")
    assert got["note"] == "People/Maya Chen.md" and got["mentions"] == 1 and not got["written"]
    assert got["timeline"][0]["day"] == "2026-10-01" and "Founder of [[Lumen Labs]]" in got["note_text"]
    assert "backlinker:dossier" not in (demo.root / "People/Maya Chen.md").read_text()
    assert call(server, "dossier", name="Maya", write=True)["written"]
    assert "backlinker:dossier" in (demo.root / "People/Maya Chen.md").read_text()


def test_guest_list_then_research_then_undo(server, demo):
    got = call(server, "guest_list", guests=["Maya Chen - Lumen", "Dee Moss, Founder at Moss Labs"],
               pick=["Dee Moss"], event="Harbor Launch")
    assert [(g["name"], g["status"]) for g in got["guests"]] == [("Maya Chen", "known"), ("Dee Moss", "new")]
    assert "People/Dee Moss.md" in got["files"] and got["files"]["Projects/Harbor Launch.md"] == ["- [[Dee Moss]]"]

    added = call(server, "add_to_dossier", name="Dee Moss", section="Key Facts",
                 lines=["Founder of Moss Labs, previously at Lumen Labs"], sources=["https://moss.example/about"])
    assert added["files"]["People/Dee Moss.md"][0] == "- Founder of Moss Labs, previously at [[Lumen Labs]]"
    text = (demo.root / "People/Dee Moss.md").read_text()
    assert "## Sources\n- https://moss.example/about\n" in text

    assert call(server, "undo_last")["undone"].startswith("mcp: Key Facts")
    assert "Moss Labs, previously" not in (demo.root / "People/Dee Moss.md").read_text()


def test_add_to_dossier_needs_a_source(server):
    async def go():
        async with Client(server) as client:
            return await client.call_tool("add_to_dossier", {"name": "Maya", "section": "Key Facts",
                                                             "lines": ["CEO"], "sources": []})
    res = anyio.run(go)
    assert res.is_error and "source" in res.content[0].text
