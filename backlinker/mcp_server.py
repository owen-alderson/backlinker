"""MCP server: lets Claude (or any MCP client) capture into the vault through the same linker.

  claude mcp add backlinker -- bl mcp
"""

import difflib
import functools
from datetime import date
from pathlib import PurePosixPath

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from backlinker import journal, safewrite
from backlinker.capture import apply, plan_capture
from backlinker.dates import parse_when
from backlinker.index import scan
from backlinker.linker import key
from backlinker.vaults import VaultError, resolve_vault

INSTRUCTIONS = """Writes to the user's Obsidian vault. `capture` adds lines to today's daily note
(or another day's) with [[links]] to existing notes added automatically; pass `to` to also add
the line to specific notes. Use `preview_links` or dry_run=true to check before writing, and
`undo_last` to take back the most recent change. Plain text in, never markdown links: the
linker adds them.

People dossiers: `dossier` returns everything the vault already says about a person (read it
before researching, so you add what's missing rather than repeat it). For an event, give
`guest_list` the names (read from any file the user shares) and the people they want to meet;
it says who they already know and starts notes for the picks. Then research each pick on the
web and record what you find with `add_to_dossier`, one section at a time, always with the
URLs it came from. Only add facts you found in a source; mark anything unconfirmed as such."""


def _explained(fn):
    """Let the model see why a call was refused (unknown note, no source...); a real crash stays generic."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (VaultError, LookupError, ValueError, safewrite.Conflict, OSError) as e:
            raise ToolError(str(e)) from e
    return wrapper


def build(vault_choice: str | None = None) -> MCPServer:
    server = MCPServer("backlinker", instructions=INSTRUCTIONS)

    @server.tool()
    @_explained
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
    @_explained
    def preview_links(text: str) -> dict:
        """Show how text would be linked, without writing anything."""
        vault = resolve_vault(vault_choice)
        cap = plan_capture(vault, text)
        return {"lines": next(iter(cap.lines.values()), []), "links": cap.links, "ambiguous": cap.ambiguous}

    @server.tool()
    @_explained
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
    @_explained
    def dossier(name: str, write: bool = False, create: bool = False) -> dict:
        """What the vault says about a person: every mention (note, line, date, text), open tasks,
        who they're mentioned with, and their note's current text.

        write: also rebuild the 'From the vault' block in their note.
        create: start a person note if there's none (implies write)."""
        from backlinker.dossier import plan_dossier

        vault = resolve_vault(vault_choice)
        cap, d = plan_dossier(vault, name, create=create)
        if (write or create) and cap.edits:
            apply(cap, f"mcp: dossier {name}")
        note = next((e.after for e in cap.edits if e.path == vault.note_path(d.rel)), None) \
            or (vault.note_path(d.rel).read_text(encoding="utf-8") if vault.note_path(d.rel).exists() else "")
        return {**d.to_dict(), "note_text": note[:20000], "written": bool((write or create) and cap.edits)}

    @server.tool()
    @_explained
    def guest_list(guests: list[str] | None = None, path: str | None = None, pick: list[str] | None = None,
                   event: str | None = None, dry_run: bool = False) -> dict:
        """Match an event's guest list against the vault's people; start notes for the picks.

        guests: one per entry, e.g. "Jane Doe - CEO, Acme" (read them from whatever the user shared),
        or path: a CSV/TSV/text file. pick: the guests the user wants to meet. event: the event's note."""
        from pathlib import Path

        from backlinker.guests import parse_line, plan_guests, read_guest_list

        vault = resolve_vault(vault_choice)
        source = Path(path).expanduser() if path else None
        if source:
            rows, label = read_guest_list(source), source.stem
        else:
            rows, label = [g for line in guests or [] if (g := parse_line(line))], "the guest list"
        cap, matches = plan_guests(vault, rows, pick or [], event=event, label=label, source=source)
        if cap.edits and not dry_run:
            apply(cap, f"mcp: guests {label}")
        return {"guests": [{"name": m.guest.name, "status": m.status, "notes": m.notes, "about": m.guest.about,
                            **m.guest.facts} for m in matches],
                "files": cap.lines, "dry_run": dry_run,
                "diff": "".join(e.diff(vault.root) for e in cap.edits) if dry_run else None}

    @server.tool()
    @_explained
    def add_to_dossier(name: str, section: str, lines: list[str], sources: list[str],
                       dry_run: bool = False) -> dict:
        """Add researched facts to a section of a person's note ("Overview", "Key Facts",
        "Background", "Connections"...), mentions linked. sources (URLs or note names) are required
        and listed under ## Sources."""
        from backlinker.dossier import plan_add

        vault = resolve_vault(vault_choice)
        cap = plan_add(vault, name, section, lines, sources)
        if dry_run:
            return {"files": cap.lines, "dry_run": True, "diff": "".join(e.diff(vault.root) for e in cap.edits)}
        if cap.edits:
            apply(cap, f"mcp: {section} for {name}")
        return {"files": cap.lines, "dry_run": False}

    @server.tool()
    @_explained
    def undo_last() -> dict:
        """Undo the most recent backlinker change to this vault."""
        vault = resolve_vault(vault_choice)
        op = journal.undo(vault.root)
        return {"undone": op["summary"], "files": [e["path"] for e in op["edits"]]}

    return server


def main(vault_choice: str | None = None) -> None:
    build(vault_choice).run()
