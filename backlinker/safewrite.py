"""Read and write notes without ever losing text.

Writes go to a hidden temp file in the same folder and are swapped in atomically, and a
write is refused if the note changed since we read it (Obsidian, sync or you editing it).
Line endings are kept as they are.
"""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


class Conflict(Exception):
    pass


@dataclass(frozen=True)
class Snapshot:
    path: Path
    text: str | None          # None: the file doesn't exist
    stamp: tuple | None

    @property
    def newline(self) -> str:
        return "\r\n" if self.text and "\r\n" in self.text else "\n"


def _stamp(path: Path) -> tuple | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return st.st_mtime_ns, st.st_size


def read(path: Path) -> Snapshot:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            text = f.read()
    except FileNotFoundError:
        return Snapshot(path, None, None)
    return Snapshot(path, text, _stamp(path))


def write(snap: Snapshot, new_text: str) -> None:
    """Replace the note's contents, unless it changed since `snap` was taken."""
    if _stamp(snap.path) != snap.stamp:
        raise Conflict(f"{snap.path.name} changed while we were writing; nothing was written to it")
    snap.path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{snap.path.name}.", suffix=".tmp", dir=snap.path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
            f.flush()
            os.fsync(f.fileno())
        if snap.stamp is None and snap.path.exists():
            raise Conflict(f"{snap.path.name} was created while we were writing; nothing was written to it")
        os.replace(tmp, snap.path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def delete(snap: Snapshot) -> None:
    if _stamp(snap.path) != snap.stamp:
        raise Conflict(f"{snap.path.name} changed; not deleting it")
    snap.path.unlink()
