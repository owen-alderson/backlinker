"""
Vault index and file operations.
Reads the vault structure and handles reading/writing notes.
"""

import json
import os
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path


CONFIG_PATH = Path.home() / ".config" / "obsidian-quick-add" / "config.json"

FOLDER_MAP = {
    "person":  "Atlas/People",
    "company": "Atlas/Companies",
    "topic":   "Atlas/Topics",
    "effort":  "Efforts",
}

CALENDAR_FOLDER = "Calendar"


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def save_config(config: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def get_vault_path() -> Path:
    config = load_config()
    if "vault" in config:
        return Path(config["vault"]).expanduser()
    # Try common default locations
    candidates = [
        Path.home() / "Documents" / "Obsidian Vault",
        Path.home() / "Obsidian Vault",
        Path.home() / "Documents" / "Obsidian",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


# ── Index ──────────────────────────────────────────────────────────────────────

def build_index(vault: Path) -> dict:
    """
    Returns a dict mapping note type to list of (name, path) tuples.
    """
    index = {k: [] for k in FOLDER_MAP}
    for note_type, folder in FOLDER_MAP.items():
        folder_path = vault / folder
        if folder_path.exists():
            for f in folder_path.glob("*.md"):
                index[note_type].append((f.stem, f))
    return index


def fuzzy_score(query: str, candidate: str) -> float:
    q, c = query.lower(), candidate.lower()
    if q in c or c in q:
        return 1.0
    return SequenceMatcher(None, q, c).ratio()


def detect_mentions(text: str, index: dict, threshold: float = 0.75) -> list[dict]:
    """
    Scans text for mentions of known vault entries.
    Returns list of {type, name, path, score}.
    """
    words = text.split()
    matches = []
    seen_paths = set()

    for note_type, entries in index.items():
        for name, path in entries:
            # Check full name and each word of the name
            score = fuzzy_score(name, text)
            # Also try sliding windows of words for multi-word names
            name_words = name.split()
            for i in range(len(words)):
                window = " ".join(words[i:i + len(name_words)])
                s = fuzzy_score(name, window)
                score = max(score, s)

            if score >= threshold and str(path) not in seen_paths:
                matches.append({"type": note_type, "name": name, "path": path, "score": score})
                seen_paths.add(str(path))

    matches.sort(key=lambda x: -x["score"])
    return matches


# ── File operations ───────────────────────────────────────────────────────────

def append_to_note(path: Path, content: str, section: str = "Notes"):
    """
    Appends a dated bullet to the appropriate section of a note.
    Creates the section if it doesn't exist.
    """
    today = date.today().strftime("%Y-%m-%d")
    entry = f"\n**{today}** — {content.strip()}"

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n\n## {section}\n{entry}\n")
        return

    text = path.read_text(encoding="utf-8")

    # Find or create the section
    section_header = f"## {section}"
    if section_header in text:
        # Append after the section header
        idx = text.index(section_header) + len(section_header)
        text = text[:idx] + entry + text[idx:]
    else:
        # Add section at the end
        text = text.rstrip() + f"\n\n## {section}\n{entry}\n"

    path.write_text(text, encoding="utf-8")


def append_to_effort(path: Path, content: str):
    """Appends a session note to an Efforts file."""
    today = date.today().strftime("%Y-%m-%d")
    entry = f"\n**{today}** — {content.strip()}\n"

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n\n## Session Notes\n{entry}")
        return

    text = path.read_text(encoding="utf-8")
    if "## Session Notes" in text:
        idx = text.index("## Session Notes") + len("## Session Notes")
        text = text[:idx] + "\n" + entry + text[idx:]
    else:
        text = text.rstrip() + f"\n\n## Session Notes\n{entry}"

    path.write_text(text, encoding="utf-8")


def write_calendar(vault: Path, content: str, cal_date: str = None):
    """Creates or appends to a Calendar note."""
    today = cal_date or date.today().strftime("%Y-%m-%d")
    cal_path = vault / CALENDAR_FOLDER / f"{today}.md"
    cal_path.parent.mkdir(parents=True, exist_ok=True)

    entry = f"- {content.strip()}"

    if not cal_path.exists():
        cal_path.write_text(
            f"---\ndate: {today}\ntags: [calendar]\n---\n\n# {today}\n\n{entry}\n"
        )
    else:
        text = cal_path.read_text(encoding="utf-8")
        cal_path.write_text(text.rstrip() + f"\n{entry}\n")


def create_new_note(vault: Path, note_type: str, name: str, content: str) -> Path:
    """Creates a brand new Atlas or Efforts note."""
    folder = FOLDER_MAP.get(note_type, "Atlas/Topics")
    path = vault / folder / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    today = date.today().strftime("%Y-%m-%d")
    tag = note_type if note_type != "effort" else "active"

    path.write_text(
        f"---\ntags: [{tag}]\n---\n\n# {name}\n\n## Notes\n\n**{today}** — {content.strip()}\n"
    )
    return path
