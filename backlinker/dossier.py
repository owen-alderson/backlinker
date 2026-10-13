"""People dossiers: everything the vault already says about a person, gathered without AI.

`bl dossier NAME` rebuilds one marked block at the end of the person's note: how often and
when they come up, open tasks that involve them, who and what they're mentioned with, and a
timeline that links back to each source note. Text outside the block is never changed, and
blocks are skipped when gathering, so one dossier never feeds another.

A mention is a line that links the note, or plain text the linker would link to it (same
precision rules as capture: whole words, unique first names, ambiguity never guessed).
"""

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import PurePosixPath

from backlinker import safewrite
from backlinker.capture import Capture, Edit, linker_for
from backlinker.dates import parse_moment
from backlinker.index import is_person, link_targets, notes_from, scan
from backlinker.linker import WIKILINK, Linker, normalise
from backlinker.notes import DOSSIER_END, DOSSIER_START, AmbiguousNote, find_note, insert_lines
from backlinker.vaults import Vault

TIMELINE = 25        # dated entries shown in the note; `--json` and MCP get them all
TASKS = 10           # open tasks shown, newest first
EXCERPT = 180        # characters per excerpt
HEADING = "## From the vault"

_TASK = re.compile(r"^\s*[-*+]\s+\[(.)\]")
_LEAD = re.compile(r"^\s*(?:(?:#{1,6}|>|[-*+]|\d+[.)])\s+)*(?:\[.\]\s+)?")
_EMBED_OR_LINK = re.compile(r"!?\[\[([^\]\n]*)\]\]")
_MDLINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\n]*\)")
_ISO = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_LABEL = re.compile(r"^\s*\w[\w ]{0,20}:\s*")   # "Who: ", "Notes: "


@dataclass
class Mention:
    source: str                 # vault-relative path of the note it's in
    line: int                   # 1-based line number
    text: str                   # the line as plain text (links shown as their text)
    day: str | None             # ISO date, when the note or the line says which day
    linked: bool                # False: plain text that the linker would link
    task: str | None = None     # "open" or "done" for task lines
    with_notes: list[str] = field(default_factory=list)  # other notes linked on the line


@dataclass
class Dossier:
    rel: str                    # the person's note
    target: str                 # how to link it
    mentions: list[Mention]

    @property
    def sources(self) -> list[str]:
        return sorted({m.source for m in self.mentions})

    @property
    def open_tasks(self) -> list[Mention]:
        return sorted((m for m in self.mentions if m.task == "open"), key=lambda m: m.day or "", reverse=True)

    @property
    def unlinked_in(self) -> list[str]:
        return sorted({m.source for m in self.mentions if not m.linked})

    def mentioned_with(self, n: int = 8) -> list[tuple[str, int]]:
        return Counter(t for m in self.mentions for t in dict.fromkeys(m.with_notes)).most_common(n)

    def to_dict(self) -> dict:
        days = sorted(m.day for m in self.mentions if m.day)
        return {"note": self.rel, "link": f"[[{self.target}]]", "mentions": len(self.mentions),
                "notes": len(self.sources), "first": days[0] if days else None, "last": days[-1] if days else None,
                "open_tasks": [asdict(m) for m in self.open_tasks],
                "mentioned_with": [{"note": t, "lines": c} for t, c in self.mentioned_with()],
                "unlinked_in": self.unlinked_in,
                "timeline": [asdict(m) for m in newest_first(self.mentions)]}


def newest_first(mentions: list[Mention]) -> list[Mention]:
    """Dated mentions newest first, then undated ones; in note order within a day."""
    in_order = sorted(mentions, key=lambda m: (m.source, m.line))
    return sorted(in_order, key=lambda m: m.day or "", reverse=True)


# ── Gathering ─────────────────────────────────────────────────────────────────

def body_lines(text: str):
    """(line number, line) outside frontmatter, code fences and dossier blocks."""
    lines = text.splitlines()
    in_front = bool(lines) and lines[0].strip() == "---"
    fence, in_block = None, False
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if in_front:
            in_front = not (n > 1 and s in ("---", "..."))
        elif in_block:
            in_block = not s.startswith(DOSSIER_END)
        elif s.startswith(DOSSIER_START):
            in_block = True
        elif fence:
            fence = None if s.startswith(fence) else fence
        elif s.startswith(("```", "~~~")):
            fence = s[:3]
        elif s:
            yield n, line


def plain(line: str) -> str:
    """A line as readable text: no list marker, checkbox, bold or link brackets."""
    def show(m: re.Match) -> str:
        inner = m.group(1).replace("\\|", "|")
        target, _, alias = inner.partition("|")
        return alias or PurePosixPath(target.split("#")[0]).name or target.split("#")[-1]
    text = _LEAD.sub("", line, count=1)
    text = _EMBED_OR_LINK.sub(show, text)
    text = _MDLINK.sub(r"\1", text)
    return re.sub(r"\s+", " ", text.replace("**", "").replace("__", "")).strip()


class _Resolver:
    """Which note a [[link]] points to, the way Obsidian resolves it (unique name or path)."""

    def __init__(self, rels: list[str]):
        self.by_path = {r[:-3].casefold(): r for r in rels}
        self.by_name: dict[str, list[str]] = {}
        for r in rels:
            self.by_name.setdefault(PurePosixPath(r).stem.casefold(), []).append(r)

    def __call__(self, link: str) -> str | None:
        t = link.strip().removesuffix(".md").casefold()
        if not t:
            return None
        if "/" in t:
            return self.by_path.get(t) or next((r for p, r in self.by_path.items() if p.endswith("/" + t)), None)
        hits = self.by_name.get(t, [])
        return hits[0] if len(hits) == 1 else None


def daily_dates(vault: Vault, rels: list[str]) -> dict[str, date]:
    """{path: day} for every daily note, read from its name with the vault's date format."""
    dn = vault.daily_notes()
    prefix = f"{dn.folder}/" if dn.folder else ""
    out = {}
    for rel in rels:
        if rel.startswith(prefix) and (d := parse_moment(rel[len(prefix):-3], dn.format)):
            out[rel] = d
    return out


def _day(rel: str, line: str, days: dict[str, date]) -> str | None:
    """The daily note it's in, else a date the line starts with ("2026-10-12 — call", or
    "- [[2026-10-12]] ..." as `bl --to` writes), else a date in the note's name."""
    if rel in days:
        return days[rel].isoformat()
    if (m := _ISO.match(plain(line))) or (m := _ISO.search(PurePosixPath(rel).stem)):
        try:
            return date.fromisoformat(m.group(1)).isoformat()
        except ValueError:
            return None
    return None


def gather(vault: Vault, rel: str, entries=None, linker: Linker | None = None,
           pending: dict[str, str] | None = None, skip: set[str] = frozenset()) -> Dossier:
    """Every mention of the note `rel` in the rest of the vault. `pending`: {path: text} for
    notes about to be written, read instead of the files on disk. `skip`: paths not to read."""
    entries = scan(vault) if entries is None else entries
    rels = [r for r, _, _ in entries]
    targets = link_targets(rels)
    linker = linker or linker_for(vault, entries)
    resolve = _Resolver(rels)
    days = daily_dates(vault, rels)

    note = next(n for (r, _, _), n in zip(entries, notes_from(entries, vault.settings.people_folders)) if r == rel)
    first = Linker._first_name(note)
    needles = {normalise(n).casefold() for n in (*note.names, first) if n and len(n) >= 2}

    mentions = []
    for src in rels:
        if src == rel or src in skip:
            continue
        try:
            text = (pending or {}).get(src) or vault.note_path(src).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n, line in body_lines(text):
            if not any(k in normalise(line).casefold() for k in needles):
                continue  # cheap filter: every mention contains one of the names
            linked_to = [resolve(m.group(1)) for m in WIKILINK.finditer(line)]
            linked = rel in linked_to
            if not linked and note.target not in linker.link(line).targets:
                continue
            task = _TASK.match(line)
            mentions.append(Mention(
                source=src, line=n, text=plain(line), day=_day(src, line, days), linked=linked,
                task=None if not task else "open" if task.group(1) in " /" else "done",
                with_notes=[targets[r] for r in dict.fromkeys(linked_to) if r and r != rel and r not in days]))
    return Dossier(rel, targets[rel], mentions)


# ── The block in the person's note ────────────────────────────────────────────

def _excerpt(m: Mention) -> str:
    t = m.text
    return t if len(t) <= EXCERPT else t[:EXCERPT].rsplit(" ", 1)[0] + " …"


def _informative(m: Mention) -> int:
    """Prefer lines that say something over 'Who: A, B' lists."""
    return len(_LABEL.sub("", m.text).split())


def render(d: Dossier, targets: dict[str, str], days: dict[str, date], nl: str = "\n") -> str:
    def src(rel: str) -> str:
        return f"[[{targets[rel]}]]"

    out = [f"{DOSSIER_START}: rebuilt by `bl dossier`; write your own notes outside this block -->", HEADING, ""]
    if not d.mentions:
        out += ["No mentions elsewhere in the vault yet.", DOSSIER_END]
        return nl.join(out)

    dated = sorted({m.day for m in d.mentions if m.day})
    span = f" · first {dated[0]} · last {dated[-1]}" if dated else ""
    out += [f"**{len(d.mentions)} mention{'s' * (len(d.mentions) != 1)} in {len(d.sources)} "
            f"note{'s' * (len(d.sources) != 1)}**{span}", ""]

    if tasks := d.open_tasks:
        out += ["**Open tasks**"] + [f"- {_excerpt(m)} ({src(m.source)})" for m in tasks[:TASKS]]
        out += [f"- … {len(tasks) - TASKS} more"] if len(tasks) > TASKS else []
        out.append("")

    if with_ := d.mentioned_with():
        out += ["**Mentioned with** " + " · ".join(f"[[{t}]] ({c})" for t, c in with_), ""]

    groups: dict[tuple, list[Mention]] = {}
    for m in d.mentions:
        groups.setdefault((m.day, m.source), []).append(m)
    timeline = sorted(((day, s) for day, s in groups if day), key=lambda k: (k[0], k[1]), reverse=True)
    if timeline:
        out.append("**Timeline**")
        for day, s in timeline[:TIMELINE]:
            ms = groups[(day, s)]
            best = max(ms, key=_informative)
            count = f" ({len(ms)})" if len(ms) > 1 else ""
            where = src(s) if s in days else f"{day} · {src(s)}"
            out.append(f"- {where}{count}: {_excerpt(best)}")
        if len(timeline) > TIMELINE:
            out.append(f"- … {len(timeline) - TIMELINE} earlier (bl dossier --json lists every mention)")
        out.append("")

    undated = Counter(m.source for m in d.mentions if not m.day)
    if undated:
        out += ["**Also in** " + " · ".join(src(s) + (f" ({c})" if c > 1 else "")
                                            for s, c in sorted(undated.items(), key=lambda x: (-x[1], x[0])))]
    else:
        out.pop()  # no trailing blank line before the end marker
    out.append(DOSSIER_END)
    return nl.join(out)


def set_block(text: str, block: str, nl: str = "\n") -> str:
    """Replace the dossier block in a note, or add it at the end."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if l.lstrip().startswith(DOSSIER_START)), None)
    if start is None:
        body = text.rstrip("\r\n")
        return (body + nl + nl if body else "") + block + nl
    end = next((i for i in range(start, len(lines)) if lines[i].strip().startswith(DOSSIER_END)), None)
    if end is None:
        raise ValueError(f"the dossier block has no end marker ({DOSSIER_END}); add it back or delete the block")
    tail = lines[end][len(lines[end].rstrip("\r\n")):] or ""
    return "".join(lines[:start]) + block + tail + "".join(lines[end + 1:])


# ── New person notes ──────────────────────────────────────────────────────────

def people_dir(vault: Vault, entries) -> str:
    """Where new person notes go: the folder that already holds most of them."""
    folders = Counter(str(PurePosixPath(r).parent) for r, _, tags in entries
                      if is_person(r, tags, vault.settings.people_folders))
    if folders:
        top = folders.most_common(1)[0][0]
        return "" if top == "." else top
    return vault.settings.people_folders[0] if vault.settings.people_folders else ""


def new_person_text(name: str, facts: list[str] = (), notes: list[str] = (), nl: str = "\n") -> str:
    out = ["---", "tags: [person]", "---", f"# {name}", "", "## Overview", "", "## Key Facts", *facts, "",
           "## Connections", "", "## Notes", *notes, "", "## Sources", ""]
    return nl.join(out)


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|#^\[\]]', " ", name).strip()


# ── Planning (shared by the CLI and MCP) ──────────────────────────────────────

def plan_dossier(vault: Vault, query: str, *, create: bool = False, entries=None) -> tuple[Capture, Dossier]:
    """Rebuild the dossier block for one note; with `create`, start a person note if there's none."""
    entries = scan(vault) if entries is None else entries
    cap = Capture(vault, date.today())
    try:
        rel = find_note(entries, query, vault.settings.people_folders)
    except AmbiguousNote:
        raise
    except LookupError:
        if not create:
            raise
        folder = people_dir(vault, entries)
        name = safe_filename(query)
        rel = f"{folder}/{name}.md" if folder else f"{name}.md"
        snap = safewrite.read(vault.note_path(rel))
        if snap.text is not None:
            raise FileExistsError(f"{rel} exists but isn't indexed (excluded folder?)")
        cap.edits.append(Edit(snap, new_person_text(name)))
        entries = sorted(entries + [(rel, [], ["person"])])

    d = gather(vault, rel, entries)
    rels = [r for r, _, _ in entries]
    path = vault.note_path(rel)
    pending = next((e for e in cap.edits if e.path == path), None)
    snap = pending.snap if pending else safewrite.read(path)
    current = pending.after if pending else (snap.text or "")
    nl = "\r\n" if "\r\n" in current else "\n"
    if d.mentions or DOSSIER_START in current:
        after = set_block(current, render(d, link_targets(rels), daily_dates(vault, rels), nl), nl)
        if pending:
            pending.after = after
        elif after != current:
            cap.edits.append(Edit(snap, after))
    cap.lines[rel] = []
    return cap, d


def plan_add(vault: Vault, query: str, section: str, lines: list[str], sources: list[str],
             entries=None) -> Capture:
    """Add researched facts to one section of a person's note, mentions linked, sources cited.

    Every call needs a source (a URL or a note): facts nobody can trace don't go in."""
    if section.strip().lstrip("#").strip().casefold() == HEADING[3:].casefold():
        raise ValueError(f"'{HEADING[3:]}' is rebuilt by bl dossier; pick another section")
    sources = [s.strip() for s in sources if s.strip()]
    if not sources:
        raise ValueError("every fact needs a source: pass the URLs or notes it came from")
    new = [l.strip() for l in lines if l.strip()]
    if not new:
        raise ValueError("nothing to add")

    entries = scan(vault) if entries is None else entries
    rel = find_note(entries, query, vault.settings.people_folders)
    linker = linker_for(vault, entries)
    own = link_targets([r for r, _, _ in entries])[rel]
    snap = safewrite.read(vault.note_path(rel))
    text = snap.text or ""
    nl = "\r\n" if "\r\n" in text else "\n"

    added = []
    for l in new:
        body = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", l)
        added.append("- " + linker.link(body, skip={own}).text)
    heading = section.strip() if section.lstrip().startswith("#") else f"## {section.strip()}"
    after = insert_lines(text, added, heading, nl)
    cited = [f"- {s}" for s in dict.fromkeys(sources) if s not in after]
    if cited:
        after = insert_lines(after, cited, "## Sources", nl)

    cap = Capture(vault, date.today())
    cap.lines[rel] = added + cited
    cap.edits = [Edit(snap, after)] if after != text else []
    return cap
