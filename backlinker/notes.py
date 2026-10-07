"""Find notes by name, and add lines to a section of a note."""

import difflib
import re
from pathlib import PurePosixPath

from backlinker.linker import Linker, key

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def notes_from(entries, people_folders):
    from backlinker.index import notes_from as build  # index imports linker; keep the import lazy
    return build(entries, people_folders)


class NoteNotFound(LookupError):
    pass


def find_note(entries: list[tuple[str, list[str], list[str]]], query: str,
              people_folders: list[str] = ("People",)) -> str:
    """Vault-relative path of the note called `query` (by name, alias, path, or a person's first name)."""
    q = key(query.removesuffix(".md"))
    hits = sorted({rel for rel, aliases, _ in entries
                   if q in (key(PurePosixPath(rel).stem), key(rel[:-3]), *map(key, aliases))})
    if not hits:
        notes = notes_from(entries, people_folders)
        hits = sorted({rel for (rel, _, _), n in zip(entries, notes)
                       if (first := Linker._first_name(n)) and key(first) == q})
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise NoteNotFound(f"{query!r} matches {len(hits)} notes: " + ", ".join(h[:-3] for h in hits))
    names = {PurePosixPath(rel).stem: rel for rel, _, _ in entries}
    close = difflib.get_close_matches(query, list(names), n=3, cutoff=0.6)
    hint = f"; did you mean {' or '.join(repr(c) for c in close)}?" if close else ""
    raise NoteNotFound(f"no note called {query!r}{hint}")


def _parse_heading(line: str) -> tuple[int, str] | None:
    m = _HEADING.match(line.rstrip("\r\n"))
    return (len(m.group(1)), m.group(2).casefold()) if m else None


def insert_lines(text: str, new: list[str], heading: str = "", nl: str = "\n") -> str:
    """Add `new` lines at the end of the section under `heading` (any level if it has no #s),
    creating the heading at the end of the note if it's missing. No heading: end of the note."""
    lines = text.splitlines(keepends=True)
    want = _parse_heading(heading) if heading.lstrip().startswith("#") else (None, heading.strip().casefold())

    # Map headings, ignoring frontmatter and fenced code.
    heads, fence = [], None
    in_front = bool(lines) and lines[0].strip() == "---"
    for i, line in enumerate(lines):
        s = line.strip()
        if in_front:
            in_front = not (i > 0 and s in ("---", "..."))
        elif fence:
            fence = None if s.startswith(fence) else fence
        elif s.startswith(("```", "~~~")):
            fence = s[:3]
        elif (h := _parse_heading(line)):
            heads.append((i, *h))

    if heading:
        found = next(((i, lvl) for i, lvl, title in heads
                      if title == want[1] and want[0] in (None, lvl)), None)
        if found is None:
            title = heading.strip() if heading.lstrip().startswith("#") else f"## {heading.strip()}"
            body = text.rstrip("\r\n")
            return (body + nl + nl if body else "") + title + nl + "".join(l + nl for l in new)
        start, lvl = found
        end = next((i for i, l, _ in heads if i > start and l <= lvl), len(lines))
    else:
        start, end = -1, len(lines)

    last = max((i for i in range(start + 1, end) if lines[i].strip()), default=start)
    if last >= 0 and not lines[last].endswith(("\n", "\r")):
        lines[last] += nl
    prev = lines[last].strip() if last >= 0 else ""
    gap = [nl] if prev and not _LIST_ITEM.match(lines[last]) and not _parse_heading(lines[last]) else []
    lines[last + 1:last + 1] = gap + [l + nl for l in new]
    return "".join(lines)
