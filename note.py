#!/usr/bin/env python3
"""
obsidian-quick-add — instantly add notes to your Obsidian vault from the terminal.

Usage:
  note add "Text to add"                    # auto-detect and route
  note person "Name" "Text"                 # add to a specific person's note
  note company "Name" "Text"               # add to a specific company's note
  note topic "Name" "Text"                 # add to a specific topic note
  note effort "Name" "Text"                # append session note to an effort
  note calendar "Text"                     # add to today's calendar
  note scan "Text"                         # show what would be detected (dry run)
  note config --vault "/path/to/vault"     # set vault path
  note config --show                       # show current config
"""

import sys
import argparse
from pathlib import Path
from vault import (
    get_vault_path, save_config, load_config, build_index,
    detect_mentions, append_to_note, append_to_effort,
    write_calendar, create_new_note, FOLDER_MAP,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def ok(msg):  print(f"  ✓  {msg}")
def info(msg): print(f"  →  {msg}")
def warn(msg): print(f"  ⚠  {msg}")
def err(msg):  print(f"  ✗  {msg}"); sys.exit(1)


def require_vault() -> Path:
    vault = get_vault_path()
    if not vault or not vault.exists():
        err(
            "Vault not found. Run:\n"
            "    note config --vault \"/path/to/your/Obsidian Vault\""
        )
    return vault


def find_note(vault: Path, note_type: str, name: str) -> Path | None:
    """Find a note by approximate name match."""
    from vault import fuzzy_score
    folder = vault / FOLDER_MAP[note_type]
    if not folder.exists():
        return None
    best_score, best_path = 0, None
    for f in folder.glob("*.md"):
        score = fuzzy_score(name, f.stem)
        if score > best_score:
            best_score, best_path = score, f
    if best_score >= 0.6:
        return best_path
    return None


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_add(text: str):
    """Auto-detect mentions and route to the best matching note."""
    vault = require_vault()
    index = build_index(vault)
    matches = detect_mentions(text, index)

    if not matches:
        # No match found — ask where to put it
        print("  No existing notes detected in your text.")
        print("  Options:")
        print("    1. Add to calendar (today)")
        print("    2. Create a new note")
        print("    3. Cancel")
        choice = input("  Choice [1/2/3]: ").strip()
        if choice == "1":
            write_calendar(vault, text)
            ok(f"Added to calendar ({vault / 'Calendar'})")
        elif choice == "2":
            note_type = input("  Type [person/company/topic/effort]: ").strip()
            name = input("  Name: ").strip()
            if note_type and name:
                path = create_new_note(vault, note_type, name, text)
                ok(f"Created {path.relative_to(vault)}")
        return

    # Show matches and let user pick (or auto-pick top match)
    if len(matches) == 1:
        m = matches[0]
        route_to(vault, m, text)
    else:
        print(f"  Detected {len(matches)} possible match(es):")
        for i, m in enumerate(matches[:5], 1):
            rel = m["path"].relative_to(vault)
            print(f"    {i}. [{m['type']}] {m['name']}  ({rel})  — score {m['score']:.0%}")
        print(f"    {len(matches[:5])+1}. Add to calendar instead")
        print(f"    0. Cancel")
        choice = input("  Route to [number]: ").strip()
        try:
            idx = int(choice)
            if idx == 0:
                return
            elif idx == len(matches[:5]) + 1:
                write_calendar(vault, text)
                ok("Added to calendar")
            else:
                route_to(vault, matches[idx - 1], text)
        except (ValueError, IndexError):
            warn("Invalid choice — cancelled.")


def route_to(vault: Path, match: dict, text: str):
    """Append text to the matched note."""
    if match["type"] == "effort":
        append_to_effort(match["path"], text)
    else:
        append_to_note(match["path"], text)
    ok(f"Appended to {match['path'].relative_to(vault)}")


def cmd_explicit(note_type: str, name: str, text: str):
    """Add to a specific named note."""
    vault = require_vault()
    path = find_note(vault, note_type, name)

    if path:
        if note_type == "effort":
            append_to_effort(path, text)
        else:
            append_to_note(path, text)
        ok(f"Appended to {path.relative_to(vault)}")
    else:
        info(f"No existing {note_type} note found for '{name}'.")
        create = input("  Create a new note? [y/n]: ").strip().lower()
        if create == "y":
            path = create_new_note(vault, note_type, name, text)
            ok(f"Created {path.relative_to(vault)}")


def cmd_calendar(text: str):
    vault = require_vault()
    write_calendar(vault, text)
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    ok(f"Added to Calendar/{today}.md")


def cmd_scan(text: str):
    """Dry run — show what would be detected."""
    vault = require_vault()
    index = build_index(vault)
    matches = detect_mentions(text, index)

    print(f"\n  Scanning: \"{text}\"\n")
    if not matches:
        info("No existing vault entries detected.")
    else:
        print(f"  Found {len(matches)} match(es):\n")
        for m in matches[:8]:
            rel = m["path"].relative_to(vault)
            print(f"    [{m['type']}] {m['name']}")
            print(f"           {rel}  (score: {m['score']:.0%})\n")


def cmd_config(vault_path: str = None, show: bool = False):
    config = load_config()
    if show:
        if config:
            print("\n  Current config:")
            for k, v in config.items():
                print(f"    {k}: {v}")
        else:
            info("No config set yet.")
        return
    if vault_path:
        p = Path(vault_path).expanduser()
        if not p.exists():
            err(f"Path does not exist: {p}")
        config["vault"] = str(p)
        save_config(config)
        ok(f"Vault set to: {p}")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) < 3:
            err("Usage: note add \"your text here\"")
        cmd_add(" ".join(sys.argv[2:]))

    elif cmd in ("person", "company", "topic", "effort"):
        if len(sys.argv) < 4:
            err(f"Usage: note {cmd} \"Name\" \"Text\"")
        name = sys.argv[2]
        text = " ".join(sys.argv[3:])
        cmd_explicit(cmd, name, text)

    elif cmd == "calendar":
        if len(sys.argv) < 3:
            err("Usage: note calendar \"your text here\"")
        cmd_calendar(" ".join(sys.argv[2:]))

    elif cmd == "scan":
        if len(sys.argv) < 3:
            err("Usage: note scan \"your text here\"")
        cmd_scan(" ".join(sys.argv[2:]))

    elif cmd == "config":
        parser = argparse.ArgumentParser()
        parser.add_argument("--vault", type=str, default=None)
        parser.add_argument("--show", action="store_true")
        args = parser.parse_args(sys.argv[2:])
        cmd_config(vault_path=args.vault, show=args.show)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
