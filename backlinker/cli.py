"""bl: capture into your Obsidian vault with the [[links]] already in place.

  bl "call with Maya about the pilot"        today's daily note, mentions linked
  bl -t "send Jonas the deck fri"            a task with a due date
  bl --to "Maya" "prefers mornings"          also add it to Maya's note
  bl --date yesterday "ran 5k"               into another day's note
  echo "..." | bl -                          from stdin, one entry per line
  bl link "Meeting notes"                    link unlinked mentions in a note
  bl triage                                  file each line of Inbox.md
  bl undo                                    take back the last change
"""

import argparse
import json
import os
import sys
from datetime import date, datetime

from backlinker import __version__, journal, safewrite
from backlinker.capture import Capture, apply, plan_capture, plan_link
from backlinker.dates import parse_when
from backlinker.index import load_notes
from backlinker.notes import NoteNotFound
from backlinker.vaults import (VaultError, coerce_setting, config_path, discover_vaults, load_config,
                               resolve_vault, save_config, SETTING_NAMES, VaultSettings)

COMMANDS = ("add", "init", "config", "link", "triage", "undo", "mcp")


class Out:
    def __init__(self, as_json: bool = False):
        self.json = as_json
        self.color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def _c(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.color else s

    def ok(self, s): print(self._c("32", "✓ ") + s)
    def warn(self, s): print(self._c("33", "? ") + s)
    def dim(self, s): print(self._c("2", s))
    def head(self, s): print(self._c("1", s))


def _vault(args):
    return resolve_vault(getattr(args, "vault", None))


def _report(out: Out, cap: Capture, dry: bool, undo_hint: bool = True) -> None:
    if out.json:
        print(json.dumps({**cap.summary(), "dry_run": dry}, ensure_ascii=False, indent=2))
        return
    if dry:
        for e in cap.edits:
            print(e.diff(cap.vault.root), end="")
    else:
        for rel, lines in cap.lines.items():
            out.head(rel)
            for line in lines:
                print("  " + line)
    if cap.links:
        out.ok("linked " + ", ".join(cap.links))
    for a in cap.ambiguous:
        out.warn(f"{a['text']!r} could be {' or '.join(a['candidates'])}; left unlinked "
                 f"(add it as an alias to the right note)")
    for d in cap.due:
        d = date.fromisoformat(d)
        out.dim(f"📅 due {d:%a} {d.day} {d:%b %Y}")
    if dry:
        out.dim("dry run: nothing was written")
    elif not cap.edits:
        out.dim("nothing to change")
    elif undo_hint:
        out.dim("undo: bl undo")


def cmd_add(args, out: Out) -> int:
    text = " ".join(args.text)
    if text in ("", "-"):
        if sys.stdin.isatty():
            print('usage: bl "text to capture"   (bl -h for more)', file=sys.stderr)
            return 2
        text = sys.stdin.read()
    if not text.strip():
        print("nothing to capture", file=sys.stderr)
        return 2
    vault = _vault(args)
    if args.heading is not None:
        vault.settings.heading = args.heading
    day = parse_when(args.date, date.today()) if args.date else None
    cap = plan_capture(vault, text, task=args.task, day=day, to=args.to or [], link=not args.no_link)
    if not args.dry_run and cap.edits:
        apply(cap, text.strip().splitlines()[0][:80])
    _report(out, cap, args.dry_run)
    return 0


def cmd_link(args, out: Out) -> int:
    vault = _vault(args)
    cap = plan_link(vault, args.note)
    if not args.dry_run and cap.edits:
        apply(cap, f"link {args.note}")
    if not out.json and not args.dry_run:
        cap.lines = {}  # the summary line says it all
        if cap.edits:
            out.head(cap.edits[0].path.relative_to(vault.root).as_posix())
    _report(out, cap, args.dry_run)
    return 0


def cmd_undo(args, out: Out) -> int:
    vault = _vault(args)
    op = journal.undo(vault.root)
    files = [os.path.relpath(e["path"], vault.root) for e in op["edits"]]
    if out.json:
        print(json.dumps({"undone": op["summary"], "files": files}, ensure_ascii=False))
    else:
        out.ok(f"undid: {op['summary']}")
        for f in files:
            out.dim("  " + f)
    return 0


def cmd_triage(args, out: Out) -> int:
    from backlinker.triage import triage

    vault = _vault(args)
    if not args.all and not sys.stdin.isatty():
        print("triage asks about each line; run it in a terminal, or use --all to file everything", file=sys.stderr)
        return 2
    counts = triage(vault, ask=input, say=print, file_all=args.all)
    out.ok(f"{counts['filed']} filed, {counts['deleted']} deleted, {counts['skipped']} left in the inbox")
    return 0


def cmd_init(args, out: Out) -> int:
    from pathlib import Path

    if args.path:
        root = Path(args.path).expanduser().resolve()
        if not root.is_dir():
            raise VaultError(f"not a folder: {root}")
    else:
        found = discover_vaults()
        if not found:
            raise VaultError("Obsidian has no vaults registered here; run `bl init /path/to/vault`")
        root = found[0]
        if len(found) > 1 and sys.stdin.isatty():
            for i, p in enumerate(found, 1):
                print(f"  {i}. {p}")
            pick = input(f"Which vault? [1-{len(found)}, enter = 1] ").strip() or "1"
            if not pick.isdigit() or not 1 <= int(pick) <= len(found):
                raise VaultError("no vault chosen")
            root = found[int(pick) - 1]

    cfg = load_config()
    name = root.name
    table = cfg["vaults"].setdefault(name, {})
    table["path"] = str(root)
    cfg["default"] = name
    save_config(cfg)

    vault = resolve_vault(name)
    dn = vault.daily_notes()
    notes = load_notes(vault)
    out.ok(f"vault: {root}")
    out.dim(f"  daily notes: {dn.folder or '(vault root)'}/{dn.format}.md"
            + (f", template {dn.template}" if dn.template else ""))
    out.dim(f"  {len(notes)} notes indexed, {sum(n.person for n in notes)} of them people")
    out.dim(f"  config: {config_path()}")
    print('\nTry:  bl -n "your first note"   (-n shows what would change without writing)')
    return 0


def cmd_config(args, out: Out) -> int:
    cfg = load_config()
    vault = _vault(args)
    name = next((n for n, t in cfg["vaults"].items() if t.get("path") == str(vault.root)), vault.name)
    if args.key:
        if args.value is None:
            print(getattr(vault.settings, args.key) if args.key in SETTING_NAMES else "", end="\n")
            return 0
        table = cfg["vaults"].setdefault(name, {"path": str(vault.root)})
        table[args.key] = coerce_setting(args.key, args.value)
        cfg.setdefault("default", name)
        save_config(cfg)
        out.ok(f"{args.key} = {table[args.key]!r}  ({name})")
        return 0
    if out.json:
        print(json.dumps({"config": str(config_path()), "vault": name, **vars(vault.settings)}, indent=2))
        return 0
    out.head(f"{name}  ({vault.root})")
    defaults = VaultSettings()
    for k in SETTING_NAMES:
        v = getattr(vault.settings, k)
        print(f"  {k} = {v!r}" + ("" if v != getattr(defaults, k) else "   (default)"))
    out.dim(f"config file: {config_path()}")
    return 0


def cmd_mcp(args, out: Out) -> int:
    try:
        from backlinker.mcp_server import main as serve
    except ImportError:
        print("the MCP server needs the mcp package:  pipx install 'backlinker[mcp]'  "
              "(or: pipx inject backlinker mcp)", file=sys.stderr)
        return 1
    serve(getattr(args, "vault", None))
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", help="vault name (from config) or path")
    common.add_argument("--json", action="store_true", help="machine-readable output")

    p = argparse.ArgumentParser(prog="bl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"backlinker {__version__}")
    sub = p.add_subparsers(dest="command")

    a = sub.add_parser("add", parents=[common], help="capture text (the default command)")
    a.add_argument("text", nargs="*", help='text to capture; "-" reads stdin')
    a.add_argument("-t", "--task", action="store_true", help="make it a task; a date phrase becomes its due date")
    a.add_argument("-d", "--date", help="file into another day's note: yesterday, fri, last fri, oct 9, 2026-10-09")
    a.add_argument("--to", action="append", metavar="NOTE", help="also add it to this note (repeatable)")
    a.add_argument("-n", "--dry-run", action="store_true", help="show the change without writing")
    a.add_argument("--no-link", action="store_true", help="don't add links")
    a.add_argument("--heading", help="daily-note heading to add under (overrides config for this run)")

    i = sub.add_parser("init", parents=[common], help="choose your vault")
    i.add_argument("path", nargs="?", help="vault folder (default: pick from Obsidian's vault list)")

    c = sub.add_parser("config", parents=[common], help="show or change settings")
    c.add_argument("key", nargs="?", choices=SETTING_NAMES, metavar="KEY")
    c.add_argument("value", nargs="?")

    l = sub.add_parser("link", parents=[common], help="link unlinked mentions in an existing note")
    l.add_argument("note", help="note name, alias or path")
    l.add_argument("-n", "--dry-run", action="store_true", help="show the change without writing")

    t = sub.add_parser("triage", parents=[common], help="file each line of your inbox note")
    t.add_argument("--all", action="store_true", help="file every line into its daily note without asking")

    sub.add_parser("undo", parents=[common], help="undo the last change")
    sub.add_parser("mcp", parents=[common], help="run the MCP server (stdio) for Claude and other clients")
    return p


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv and sys.stdin.isatty():
        build_parser().print_help()
        return 0
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "add")
    args = build_parser().parse_args(argv)
    out = Out(getattr(args, "json", False))
    handler = {"add": cmd_add, "init": cmd_init, "config": cmd_config, "link": cmd_link,
               "triage": cmd_triage, "undo": cmd_undo, "mcp": cmd_mcp}[args.command]
    try:
        return handler(args, out)
    except (VaultError, NoteNotFound, safewrite.Conflict, ValueError, LookupError, FileNotFoundError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # ✓ and 📅 must not crash a Windows pipe
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(run())


if __name__ == "__main__":
    main()
