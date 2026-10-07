"""An undo journal: each capture records the notes it touched, before and after."""

import json
import time
import uuid
from pathlib import Path

from backlinker import safewrite
from backlinker.vaults import state_dir

KEEP = 100  # operations remembered


def _file() -> Path:
    return state_dir() / "journal.jsonl"


def _load() -> list[dict]:
    try:
        lines = _file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    ops = []
    for line in lines:
        try:
            ops.append(json.loads(line))
        except ValueError:
            continue
    return ops


def _save(ops: list[dict]) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(op, ensure_ascii=False) + "\n" for op in ops[-KEEP:]), encoding="utf-8")


def record(vault: Path, summary: str, edits: list[tuple[Path, str | None, str]]) -> str:
    op = {"id": uuid.uuid4().hex[:12], "time": time.time(), "vault": str(vault), "summary": summary,
          "edits": [{"path": str(p), "before": b, "after": a} for p, b, a in edits]}
    _save(_load() + [op])
    return op["id"]


def last(vault: Path) -> dict | None:
    return next((op for op in reversed(_load()) if op["vault"] == str(vault)), None)


def _inserted(before: str, after: str) -> str | None:
    """The single block that turned `before` into `after`, if that's all that happened."""
    if len(after) <= len(before):
        return None
    p = 0
    while p < len(before) and before[p] == after[p]:
        p += 1
    s = 0
    while s < len(before) - p and before[len(before) - 1 - s] == after[len(after) - 1 - s]:
        s += 1
    return after[p:len(after) - s] if p + s == len(before) else None


def undo(vault: Path) -> dict:
    """Undo the vault's most recent operation, all-or-nothing.

    A note nobody touched since is restored exactly. A note edited since keeps those edits:
    only our inserted block is taken out, and only if it appears exactly once. Anything else
    is refused and nothing is changed."""
    op = last(vault)
    if not op:
        raise LookupError("nothing to undo")
    plan = []
    for e in reversed(op["edits"]):
        snap = safewrite.read(Path(e["path"]))
        if snap.text == e["after"]:
            plan.append((snap, e["before"]))
            continue
        block = _inserted(e["before"] or "", e["after"])
        if e["before"] is not None and snap.text and block and snap.text.count(block) == 1:
            plan.append((snap, snap.text.replace(block, "", 1)))
            continue
        name = Path(e["path"]).name
        raise safewrite.Conflict(f"{name} was changed in a way undo can't safely reverse; nothing was undone")
    for snap, text in plan:
        if text is None:
            safewrite.delete(snap)
        else:
            safewrite.write(snap, text)
    _save([o for o in _load() if o["id"] != op["id"]])
    return op
