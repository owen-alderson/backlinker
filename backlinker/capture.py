"""Capture: turn a line of text into edits on the vault. Shared by the CLI, triage and MCP.

`plan_capture` works out every edit without writing anything (that is --dry-run);
`apply` writes them all and records one undo step.
"""

import difflib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from backlinker import daily, journal, safewrite
from backlinker.dates import find_due
from backlinker.index import load_notes, scan, notes_from
from backlinker.linker import PROTECTED, Linker, Result
from backlinker.notes import find_note, insert_lines
from backlinker.vaults import Vault

_TASK = re.compile(r"^(?:[-*+]\s+)?(?:\[ ?\]\s*|todo:?\s+)", re.IGNORECASE)
_BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


@dataclass
class Edit:
    snap: safewrite.Snapshot
    after: str

    @property
    def path(self) -> Path:
        return self.snap.path

    def diff(self, root: Path) -> str:
        rel = self.path.relative_to(root).as_posix()
        return "".join(difflib.unified_diff(
            (self.snap.text or "").splitlines(keepends=True), self.after.splitlines(keepends=True),
            fromfile="/dev/null" if self.snap.text is None else rel, tofile=rel))


@dataclass
class Capture:
    vault: Vault
    day: date
    edits: list[Edit] = field(default_factory=list)
    lines: dict[str, list[str]] = field(default_factory=dict)   # vault-relative path -> added lines
    links: list[str] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)
    due: list[str] = field(default_factory=list)
    op_id: str | None = None

    def summary(self) -> dict:
        return {"vault": str(self.vault.root), "date": self.day.isoformat(), "files": self.lines,
                "links": self.links, "ambiguous": self.ambiguous, "due": self.due, "undo_id": self.op_id}


def linker_for(vault: Vault, entries=None) -> Linker:
    notes = notes_from(entries, vault.settings.people_folders) if entries is not None else load_notes(vault)
    return Linker(notes, ignore=vault.settings.ignore)


def _edit(edits: dict, path: Path, change) -> None:
    """Chain changes to the same file into one edit."""
    if path not in edits:
        edits[path] = Edit(safewrite.read(path), None)
        edits[path].after = edits[path].snap.text
    edits[path].after = change(edits[path].after)


def plan_capture(vault: Vault, text: str, *, task: bool = False, day: date | None = None,
                 to: list[str] = (), link: bool = True, now: datetime | None = None,
                 entries=None) -> Capture:
    now = now or datetime.now()
    day = day or now.date()
    entries = scan(vault) if entries is None else entries
    linker = linker_for(vault, entries)
    s = vault.settings
    targets = [find_note(entries, name, s.people_folders) for name in to]   # fails before anything is planned
    daily_rel = daily.daily_rel(vault, day)
    cap = Capture(vault, day)
    edits: dict[Path, Edit] = {}

    def link_text(t: str, skip: set[str]) -> Result:
        return linker.link(t, skip=skip) if link else Result(t)

    daily_lines, note_lines = [], {rel: [] for rel in targets}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        is_task = task
        if m := _TASK.match(line):
            is_task, line = True, line[m.end():].strip()
        else:
            line = _BULLET.sub("", line, count=1)
        suffix = ""
        if is_task:
            protected = [m.span() for m in PROTECTED.finditer(line)]
            due, line = find_due(line, day, protected)
            if due:
                suffix = f" 📅 {due.isoformat()}" if s.due_format == "tasks" else f" [due:: {due.isoformat()}]"
                cap.due.append(due.isoformat())
        if not line:
            continue

        r = link_text(line, set())
        cap.links += [t for t in r.targets if t not in cap.links]
        cap.ambiguous += [a for a in r.ambiguous if a not in cap.ambiguous]
        if is_task and targets:
            pass  # a task lives in the note it's about, not twice
        elif is_task:
            daily_lines.append(f"- [ ] {r.text}{suffix}")
        else:
            stamp = f"{now:%H:%M} " if s.time_prefix and day == now.date() else ""
            daily_lines.append(f"- {stamp}{r.text}")

        for rel in targets:
            own = rel[:-3]
            nr = link_text(line, {own})
            note_lines[rel].append(f"- [ ] {nr.text}{suffix}" if is_task
                                   else f"- [[{daily.daily_link(vault, day)}]] {nr.text}")

    if daily_lines:
        path = daily.daily_path(vault, day)

        def add_daily(t: str | None) -> str:
            start = daily.new_daily_text(vault, day, now) if t is None else t
            nl = "\r\n" if "\r\n" in start else "\n"
            return insert_lines(start, daily_lines, s.heading, nl)

        _edit(edits, path, add_daily)
        cap.lines[daily_rel] = daily_lines

    for rel, new in note_lines.items():
        if not new:
            continue
        nl = "\r\n" if "\r\n" in (safewrite.read(vault.note_path(rel)).text or "") else "\n"
        _edit(edits, vault.note_path(rel), lambda t, new=new, nl=nl: insert_lines(t or "", new, s.notes_heading, nl))
        cap.lines.setdefault(rel, []).extend(new)

    cap.edits = [e for e in edits.values() if e.after != e.snap.text]
    return cap


def apply(cap: Capture, summary: str) -> str:
    """Write every planned edit, then record them as one undo step."""
    done = []
    try:
        for e in cap.edits:
            safewrite.write(e.snap, e.after)
            done.append((e.path, e.snap.text, e.after))
    finally:
        if done:  # even after a failure, whatever was written can be undone
            cap.op_id = journal.record(cap.vault.root, summary, done)
    return cap.op_id


def plan_link(vault: Vault, query: str) -> Capture:
    """Link unlinked mentions in an existing note (`bl link`)."""
    entries = scan(vault)
    path = Path(query).expanduser()
    if path.suffix == ".md" and path.is_file():
        path = path.resolve()
        rel = path.relative_to(vault.root.resolve()).as_posix()
    else:
        rel = find_note(entries, query, vault.settings.people_folders)
        path = vault.note_path(rel)
    targets = {r: t.target for r, t in zip((e[0] for e in entries), notes_from(entries, vault.settings.people_folders))}
    snap = safewrite.read(path)
    if snap.text is None:
        raise FileNotFoundError(rel)
    r = linker_for(vault, entries).link_document(snap.text, self_target=targets.get(rel, rel[:-3]))
    cap = Capture(vault, date.today(), links=r.targets, ambiguous=r.ambiguous)
    if r.text != snap.text:
        cap.edits = [Edit(snap, r.text)]
        cap.lines[rel] = [f"[[{l.target}]] ← {l.text!r}" for l in r.links]
    return cap
