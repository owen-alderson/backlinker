"""Guest lists: who on an event's list you already know, and dossiers for the ones you pick.

  bl guests founders-night.csv                       who's known, new or ambiguous
  bl guests list.txt --pick "Jane Doe" --pick Omar   start or refresh their People notes

A guest matches a person note only by exact full name or alias. A near match (same first and
last name with a middle name in between, or a lone first name) is reported, never merged, so
no person gets two notes.
"""

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from backlinker import daily, safewrite
from backlinker.capture import Capture, Edit
from backlinker.dossier import gather, new_person_text, people_dir, render, safe_filename, set_block, daily_dates
from backlinker.index import is_person, link_targets, scan
from backlinker.linker import key
from backlinker.notes import find_note, insert_lines
from backlinker.vaults import Vault

NAME_COLUMNS = ("name", "full name", "guest", "guest name", "attendee", "attendee name", "contact", "contact name")
FIRST_COLUMNS = ("first name", "firstname", "given name", "first")
LAST_COLUMNS = ("last name", "lastname", "surname", "family name", "last")
FACT_COLUMNS = {"Title": ("title", "job title", "role", "position"),
                "Company": ("company", "company name", "organization", "organisation", "employer"),
                "Email": ("email", "email address", "e-mail"),
                "LinkedIn": ("linkedin", "linkedin url", "linkedin profile")}
_LEAD = re.compile(r"^\s*(?:[-*+]\s+(?:\[.\]\s+)?|\d+[.)]\s+)")
_SPLIT = re.compile(r"\s+[-–—|]\s+|\t|,\s*|\s+\(")


@dataclass
class Guest:
    name: str
    about: str = ""                                         # what followed the name on its line
    facts: dict[str, str] = field(default_factory=dict)     # from CSV columns


@dataclass
class Match:
    guest: Guest
    status: str                 # "known", "new", "ambiguous" or "maybe"
    notes: list[str] = field(default_factory=list)          # matching (or near-matching) note paths


def parse_line(line: str) -> Guest | None:
    """'Jane Doe - CEO, Acme' -> Guest('Jane Doe', about='CEO, Acme')."""
    line = _LEAD.sub("", line.strip()).strip()
    if not line or line.startswith("#"):
        return None
    parts = _SPLIT.split(line, maxsplit=1)
    name = parts[0].strip(" *_")
    about = parts[1].strip().rstrip(")").strip() if len(parts) > 1 else ""
    return Guest(name, about) if re.search(r"[^\W\d_]", name) else None


def read_guest_list(path: Path) -> list[Guest]:
    """A CSV/TSV export (Luma, Eventbrite, a spreadsheet) or a text/markdown list, one guest per line."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() not in (".csv", ".tsv"):
        return [g for line in text.splitlines() if (g := parse_line(line))]

    rows = list(csv.reader(text.splitlines(), delimiter="\t" if path.suffix.lower() == ".tsv" else ","))
    if not rows:
        return []
    cols = {h.strip().casefold(): i for i, h in enumerate(rows[0])}

    def col(names):
        return next((cols[n] for n in names if n in cols), None)

    name, first, last = col(NAME_COLUMNS), col(FIRST_COLUMNS), col(LAST_COLUMNS)
    if name is None and first is None:
        raise ValueError(f"{path.name}: no name column (looked for {', '.join(NAME_COLUMNS[:2])}, "
                         f"or first name + last name)")
    facts = {label: i for label, names in FACT_COLUMNS.items() if (i := col(names)) is not None}

    def cell(row, i):
        return row[i].strip() if i is not None and i < len(row) else ""

    guests = []
    for row in rows[1:]:
        full = cell(row, name) or " ".join(filter(None, (cell(row, first), cell(row, last))))
        if full:
            guests.append(Guest(full, facts={k: v for k, i in facts.items() if (v := cell(row, i))}))
    return guests


def match(guests: list[Guest], entries, people_folders) -> list[Match]:
    people = [(rel, [PurePosixPath(rel).stem, *aliases]) for rel, aliases, tags in entries
              if is_person(rel, tags, people_folders)]
    out = []
    for g in guests:
        k = key(g.name)
        exact = sorted({rel for rel, names in people if k in map(key, names)})
        if len(exact) == 1:
            out.append(Match(g, "known", exact))
        elif exact:
            out.append(Match(g, "ambiguous", exact))
        else:
            toks = k.split()   # near: same first + last name, or a lone first name ("Sam")
            near = sorted({rel for rel, names in people for n in names if (nt := key(n).split()) and len(nt) >= 2
                           and ((nt[0], nt[-1]) == (toks[0], toks[-1]) if len(toks) >= 2 else nt[0] == toks[0])})
            out.append(Match(g, "maybe" if near else "new", near))
    return out


def resolve_picks(matches: list[Match], picks: list[str]) -> list[Match]:
    """Each pick names one guest: full name, or a first name only one guest has."""
    chosen = []
    for p in picks:
        k = key(p)
        hits = [m for m in matches if key(m.guest.name) == k] or \
               [m for m in matches if " " not in k and key(m.guest.name).split()[:1] == [k]]
        if not hits:
            raise LookupError(f"{p!r} isn't on the guest list")
        if len(hits) > 1:
            raise LookupError(f"{p!r} could be " + " or ".join(m.guest.name for m in hits) + "; use the full name")
        if hits[0] not in chosen:
            chosen.append(hits[0])
    return chosen


def plan_guests(vault: Vault, guests: list[Guest], picks: list[str], *, event: str | None = None,
                label: str = "the guest list", source: Path | None = None, today: date | None = None,
                entries=None) -> tuple[Capture, list[Match]]:
    """Match the list; for each pick, start a person note (new) or note the event and refresh the
    dossier block (known). Near and ambiguous matches are refused rather than guessed.
    `source`: the list's file; when it's in the vault it isn't counted as a mention."""
    today = today or date.today()
    entries = scan(vault) if entries is None else entries
    s = vault.settings
    matches = match(guests, entries, s.people_folders)
    chosen = resolve_picks(matches, picks)
    for m in chosen:
        if m.status in ("ambiguous", "maybe"):
            notes = " or ".join(PurePosixPath(r).stem for r in m.notes)
            raise LookupError(f"{m.guest.name!r} is close to {notes}; add the guest's name as an alias "
                              f"to the right note (or rename it) and run again")

    event_rel = None
    if event:
        try:
            event_rel = find_note(entries, event, s.people_folders)
        except LookupError:
            event_rel = None  # the link is still written; Obsidian offers to create the note
    event_link = f"[[{link_targets([r for r, _, _ in entries])[event_rel]}]]" if event_rel else \
        (f"[[{event}]]" if event else label)

    cap = Capture(vault, today)
    edits: dict[Path, Edit] = {}
    folder = people_dir(vault, entries)
    stamp = f"[[{daily.daily_link(vault, today)}]]"
    for m in chosen:
        g = m.guest
        detail = g.about or ", ".join(v for k, v in g.facts.items() if k in ("Title", "Company"))
        line = f"- {stamp} on the guest list for {event_link}" + (f" ({detail})" if detail else "")
        if m.status == "known":
            rel = m.notes[0]
            snap = safewrite.read(vault.note_path(rel))
            text = snap.text or ""
            nl = "\r\n" if "\r\n" in text else "\n"
            after = insert_lines(text, [line], s.notes_heading, nl) if line not in text else text
        else:
            rel = f"{folder}/{safe_filename(g.name)}.md" if folder else f"{safe_filename(g.name)}.md"
            snap = safewrite.read(vault.note_path(rel))
            if snap.text is not None:
                raise FileExistsError(f"{rel} exists but isn't a person note; tag it #person or add an alias")
            facts = [f"- **{k}:** {v}" for k, v in g.facts.items()] + ([f"- **About:** {g.about}"] if g.about else [])
            after = new_person_text(g.name, facts, [line])
            entries = sorted(entries + [(rel, [], ["person"])])
            m.notes = [rel]
        edits[vault.note_path(rel)] = Edit(snap, after)
        cap.lines[rel] = [line]

    rels = [r for r, _, _ in entries]
    targets, days = link_targets(rels), daily_dates(vault, rels)
    if event_rel and chosen:
        snap = safewrite.read(vault.note_path(event_rel))
        text = snap.text or ""
        new = [f"- [[{targets[m.notes[0]]}]]" for m in chosen if f"[[{targets[m.notes[0]]}]]" not in text]
        if new:
            nl = "\r\n" if "\r\n" in text else "\n"
            edits[vault.note_path(event_rel)] = Edit(snap, insert_lines(text, new, "## People to meet", nl))
            cap.lines[event_rel] = new

    # Refresh each pick's dossier block, counting what this run is about to write.
    skip = set()
    if source and source.resolve().is_relative_to(vault.root.resolve()):
        skip.add(source.resolve().relative_to(vault.root.resolve()).as_posix())
    pending = {e.path.relative_to(vault.root).as_posix(): e.after for e in edits.values()}
    for m in chosen:
        e = edits[vault.note_path(m.notes[0])]
        d = gather(vault, m.notes[0], entries, pending=pending, skip=skip)
        if d.mentions:
            nl = "\r\n" if "\r\n" in e.after else "\n"
            e.after = set_block(e.after, render(d, targets, days, nl), nl)

    cap.edits = [e for e in edits.values() if e.after != e.snap.text]
    return cap, matches
