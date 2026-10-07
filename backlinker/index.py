"""Index every note in a vault: its name, frontmatter aliases and tags.

Only frontmatter is read, and a small cache keyed on each file's mtime means repeat
runs only re-read the notes that changed.
"""

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath

from backlinker.linker import Note
from backlinker.vaults import Vault, cache_dir

_KEY = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")


def _scalar(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    return s


def _split_list(s: str) -> list[str]:
    """Split a YAML flow list on commas that aren't inside quotes."""
    parts, cur, quote = [], "", None
    for ch in s:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == ",":
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    return parts + [cur]


def _values(inline: str, block: list[str]) -> list[str]:
    inline = inline.strip()
    if inline.startswith("[") and inline.endswith("]"):
        items = [_scalar(x) for x in _split_list(inline[1:-1])]
    elif inline:
        items = [_scalar(inline)]
    else:
        items = [_scalar(b) for b in block]
    return [i for i in items if i]


def read_frontmatter(text: str) -> dict[str, list[str]]:
    """Read `aliases`/`alias` and `tags`/`tag` from YAML frontmatter (the forms Obsidian writes)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {"aliases": [], "tags": []}
    out = {"aliases": [], "tags": []}
    key, inline, block = None, "", []

    def flush():
        if key in ("aliases", "alias"):
            out["aliases"] += _values(inline, block)
        elif key in ("tags", "tag"):
            out["tags"] += [t.lstrip("#") for v in _values(inline, block) for t in v.split()]

    for line in lines[1:]:
        if line.strip() in ("---", "..."):
            break
        m = _KEY.match(line)
        if m:
            flush()
            key, inline, block = m.group(1).lower(), m.group(2), []
        elif line.lstrip().startswith("- ") and key:
            block.append(line.lstrip()[2:])
    flush()
    return out


def _head(path: Path, limit: int = 16384) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return f.read(limit)


def scan(vault: Vault) -> list[tuple[str, list[str], list[str]]]:
    """[(vault-relative posix path, aliases, tags)] for every note, using the mtime cache."""
    root = vault.root
    skip = {e.strip("/") for e in vault.settings.exclude if e.strip("/")}
    if vault.templates()["folder"]:
        skip.add(vault.templates()["folder"])

    cache_file = cache_dir() / (hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:16] + ".json")
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}

    fresh, changed = {}, False
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = PurePosixPath(Path(dirpath).relative_to(root).as_posix())
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and (rel_dir / d).as_posix() not in skip]
        for name in filenames:
            if not name.endswith(".md") or name.startswith("."):
                continue
            rel = (rel_dir / name).as_posix()
            path = Path(dirpath) / name
            try:
                st = path.stat()
            except OSError:
                continue
            hit = cache.get(rel)
            if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
                fresh[rel] = hit
                continue
            try:
                fm = read_frontmatter(_head(path))
            except OSError:
                continue
            fresh[rel] = [st.st_mtime_ns, st.st_size, fm["aliases"], fm["tags"]]
            changed = True

    if changed or len(fresh) != len(cache):
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # the cache is only an optimisation
    return [(rel, v[2], v[3]) for rel, v in sorted(fresh.items())]


def link_targets(paths: list[str]) -> dict[str, str]:
    """What to write inside [[ ]] for each note: the bare name, or the path when names clash."""
    stems: dict[str, int] = {}
    for p in paths:
        stem = PurePosixPath(p).stem.casefold()
        stems[stem] = stems.get(stem, 0) + 1
    return {p: (PurePosixPath(p).stem if stems[PurePosixPath(p).stem.casefold()] == 1 else p[:-3])
            for p in paths}


def is_person(rel: str, tags: list[str], people_folders: list[str]) -> bool:
    folders = {f.casefold() for f in people_folders}
    in_folder = any(part.casefold() in folders for part in PurePosixPath(rel).parent.parts)
    tagged = any({"person", "people"} & set(t.casefold().split("/")) for t in tags)
    return in_folder or tagged


def notes_from(entries: list[tuple[str, list[str], list[str]]], people_folders: list[str]) -> list[Note]:
    targets = link_targets([rel for rel, _, _ in entries])
    return [
        Note(target=targets[rel], names=(PurePosixPath(rel).stem, *aliases),
             person=is_person(rel, tags, people_folders))
        for rel, aliases, tags in entries
    ]


def load_notes(vault: Vault) -> list[Note]:
    return notes_from(scan(vault), vault.settings.people_folders)
