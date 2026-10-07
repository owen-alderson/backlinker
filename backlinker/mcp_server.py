"""MCP server: lets Claude (or any MCP client) capture into the vault through the same linker.

  claude mcp add backlinker -- bl mcp
"""

import difflib
from datetime import date
from pathlib import PurePosixPath

from mcp.server.mcpserver import MCPServer

from backlinker import journal
from backlinker.capture import apply, plan_capture
from backlinker.dates import parse_when
from backlinker.index import scan
from backlinker.linker import key
from backlinker.vaults import resolve_vault

INSTRUCTIONS = """Writes to the user's Obsidian vault. `capture` adds lines to today's daily note
(or another day's) with [[links]] to existing notes added automatically; pass `to` to also add
the line to specific notes. Use `preview_links` or dry_run=true to check before writing, and
`undo_last` to take back the most recent change. Plain text in, never markdown links: the
linker adds them."""


def build(vault_choice: str | None = None) -> MCPServer:
    server = MCPServer("backlinker", instructions=INSTRUCTIONS)

    @server.tool()
    def capture(text: str, task: bool = False, day: str | None = None, to: list[str] | None = None,
                dry_run: bool = False) -> dict:
        """Add text to a daily note with mentions of existing notes linked. One entry per line.

        task: make each line a task; a date phrase in it (fri, tomorrow, oct 9) becomes the due date.
        day: which day's note: yesterday, fri, last fri, oct 9, 2026-10-09 (default today).
        to: note names to also add the line to.
        dry_run: return the diff without writing."""
        vault = resolve_vault(vault_choice)
        when = parse_when(day, date.today()) if day else None
        cap = plan_capture(vault, text, task=task, day=when, to=to or [])
        if dry_run:
            return {**cap.summary(), "dry_run": True, "diff": "".join(e.diff(vault.root) for e in cap.edits)}
        if cap.edits:
            apply(cap, f"mcp: {text.strip()[:60]}")
        return {**cap.summary(), "dry_run": False}

    @server.tool()
    def preview_links(text: str) -> dict:
        """Show how text would be linked, without writing anything."""
        vault = resolve_vault(vault_choice)
        cap = plan_capture(vault, text)
        return {"lines": next(iter(cap.lines.values()), []), "links": cap.links, "ambiguous": cap.ambiguous}

    @server.tool()
    def find_note(query: str, limit: int = 10) -> list[dict]:
        """Find notes whose name or alias matches the query (exact and close matches)."""
        vault = resolve_vault(vault_choice)
        q = key(query)
        rows = []
        for rel, aliases, tags in scan(vault):
            names = [PurePosixPath(rel).stem, *aliases]
            score = max((1.0 if q and q in key(n) else difflib.SequenceMatcher(None, q, key(n)).ratio())
                        for n in names)
            if score >= 0.6:
                rows.append((-score, rel, {"path": rel, "name": names[0], "aliases": aliases, "tags": tags}))
        return [r[2] for r in sorted(rows, key=lambda r: r[:2])[:limit]]

    @server.tool()
    def undo_last() -> dict:
        """Undo the most recent backlinker change to this vault."""
        vault = resolve_vault(vault_choice)
        op = journal.undo(vault.root)
        return {"undone": op["summary"], "files": [e["path"] for e in op["edits"]]}

    return server


def main(vault_choice: str | None = None) -> None:
    build(vault_choice).run()
