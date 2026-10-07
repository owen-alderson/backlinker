import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from backlinker import vaults
from backlinker.vaults import Vault, VaultSettings

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo-vault"
SPEC = ROOT / "spec"
NOW = datetime(2026, 10, 7, 14, 32)  # a Wednesday


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """No test reads or writes the real config, cache, journal or Obsidian vault list."""
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(var, str(tmp_path / "xdg" / var))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("BACKLINKER_VAULT", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(vaults, "obsidian_registry_paths", lambda: [tmp_path / "obsidian.json"])
    # Tests write fixtures with "\n"; don't let Windows turn them into "\r\n" behind our back.
    original = Path.write_text
    monkeypatch.setattr(Path, "write_text", lambda self, data, encoding="utf-8", errors=None, newline="":
                        original(self, data, encoding, errors, newline))


@pytest.fixture
def registry(tmp_path):
    """Write Obsidian's vault list: registry({path: {"open": True, "ts": 1}})."""
    def write(entries: dict):
        data = {"vaults": {f"id{i}": {"path": str(p), **meta} for i, (p, meta) in enumerate(entries.items())}}
        (tmp_path / "obsidian.json").write_text(json.dumps(data))
    return write


@pytest.fixture
def demo(tmp_path) -> Vault:
    root = tmp_path / "demo"
    shutil.copytree(DEMO, root)
    return Vault(root=root, name="demo", settings=VaultSettings(path=str(root), heading="## Log"))


@pytest.fixture
def make_vault(tmp_path):
    """make_vault({"People/Ann Lee.md": "...", ".obsidian/daily-notes.json": {...}}, heading=...)"""
    def make(files: dict, **settings) -> Vault:
        root = tmp_path / "v"
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(content) if isinstance(content, dict) else content, encoding="utf-8", newline="")
        root.mkdir(exist_ok=True)
        return Vault(root=root, name="v", settings=VaultSettings(path=str(root), **settings))
    return make


def read(vault: Vault, rel: str) -> str:
    return (vault.root / rel).read_text(encoding="utf-8")
