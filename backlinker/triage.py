"""Empty an inbox note one line at a time: each line gets linked and filed, then leaves the inbox.

Jot into Inbox.md from anywhere (Obsidian mobile, Drafts, an Apple Shortcut), then run
`bl triage` on the Mac. A line leaves the inbox in the same undo step that files it, and
only after it has been written to its new home.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Callable

from backlinker import safewrite
from backlinker.capture import Capture, Edit, apply, plan_capture
from backlinker.index import scan
from backlinker.vaults import Vault

_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}):(\d{2}))?(?:\s*[-–—:|]\s*|\s+)")
_ITEM = re.compile(r"^[-*+]\s+(?:\[ \]\s+)?")
_DONE = re.compile(r"^[-*+]\s+\[[xX]\]\s")

HELP = "[enter] file  [t] task  [n] into a note  [s] skip  [d] delete  [q] quit"


@dataclass
class Item:
    block: str      # the exact lines in the inbox, newlines included
    text: str       # what gets captured
    day: date | None
    at: time | None


def items(text: str) -> list[Item]:
    """Top-level lines of the inbox; indented lines below one belong to it."""
    out, lines = [], text.splitlines(keepends=True)
    in_front = bool(lines) and lines[0].strip() == "---"
    skipping = True  # indented lines under a skipped line (a heading, a done task) are skipped too
    for i, line in enumerate(lines):
        s = line.strip()
        if in_front:
            in_front = not (i > 0 and s in ("---", "..."))
            continue
        if line[:1] in (" ", "\t") and s:
            if out and not skipping:
                out[-1].block += line
                out[-1].text += " " + _ITEM.sub("", s)
            continue
        skipping = not s or s.startswith("#") or bool(_DONE.match(s))
        if skipping:
            continue
        body = _ITEM.sub("", s) if _ITEM.match(s) else s
        if _ITEM.match(s) and s.startswith(("- [ ]", "* [ ]", "+ [ ]")):
            body = "[ ] " + body
        day = at = None
        if m := _STAMP.match(body):
            try:
                day = date.fromisoformat(m.group(1))
                at = time(int(m.group(2)), int(m.group(3))) if m.group(2) else None
                body = body[m.end():]
            except ValueError:
                pass
        out.append(Item(line, body, day, at))
    return out


def _remove(vault: Vault, rel: str, block: str) -> Edit:
    snap = safewrite.read(vault.note_path(rel))
    if not snap.text or block not in snap.text:
        raise safewrite.Conflict(f"that line is no longer in {rel}; left everything as it was")
    return Edit(snap, snap.text.replace(block, "", 1))


def file_item(vault: Vault, item: Item, *, task: bool = False, to: list[str] = (), entries=None,
              now: datetime | None = None):
    now = now or datetime.now()
    day = item.day or now.date()
    when = datetime.combine(day, item.at) if item.at else now
    cap = plan_capture(vault, item.text, task=task, day=day, to=to, now=when, entries=entries)
    cap.edits.append(_remove(vault, vault.settings.inbox, item.block))  # last: after the filing
    apply(cap, f"triage: {item.text[:60]}")
    return cap


def triage(vault: Vault, ask: Callable[[str], str], say: Callable[[str], None], file_all: bool = False,
           now: datetime | None = None) -> dict:
    rel = vault.settings.inbox if vault.settings.inbox.endswith(".md") else vault.settings.inbox + ".md"
    vault.settings.inbox = rel
    snap = safewrite.read(vault.note_path(rel))
    todo = items(snap.text or "")
    counts = {"filed": 0, "deleted": 0, "skipped": 0}
    if not todo:
        say(f"{rel} is empty, nothing to triage.")
        return counts
    entries = scan(vault)
    say(f"{len(todo)} line(s) in {rel}.  {HELP}")
    for n, item in enumerate(todo, 1):
        preview = plan_capture(vault, item.text, day=item.day or (now or datetime.now()).date(),
                               entries=entries, now=now)
        target, lines = next(iter(preview.lines.items()), ("", [item.text]))
        say(f"\n[{n}/{len(todo)}] {item.text}\n   → {target}: {' / '.join(lines)}")
        for a in preview.ambiguous:
            say(f"   ? {a['text']!r} could be {', '.join(a['candidates'])}; left unlinked")
        while True:
            choice = "" if file_all else ask("   > ").strip().lower()
            try:
                if choice in ("", "f"):
                    file_item(vault, item, entries=entries, now=now)
                elif choice == "t":
                    file_item(vault, item, task=True, entries=entries, now=now)
                elif choice == "n":
                    name = ask("   note: ").strip()
                    if not name:
                        continue
                    file_item(vault, item, to=[name], entries=entries, now=now)
                elif choice == "d":
                    cap = Capture(vault, date.today(), edits=[_remove(vault, rel, item.block)])
                    apply(cap, f"triage delete: {item.text[:60]}")
                    counts["deleted"] += 1
                    say("   deleted")
                    break
                elif choice == "s":
                    counts["skipped"] += 1
                    break
                elif choice == "q":
                    return counts
                else:
                    say(f"   {HELP}")
                    continue
            except LookupError as e:
                say(f"   ✗ {e}")
                continue
            except (safewrite.Conflict, OSError) as e:
                say(f"   ✗ {e}")
                counts["skipped"] += 1
                break
            counts["filed"] += 1
            say("   ✓ filed")
            break
    return counts
