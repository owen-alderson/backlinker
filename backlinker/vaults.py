"""Find vaults, read their Obsidian settings, and load/save backlinker's own config."""

import json
import os
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


class VaultError(Exception):
    pass


# ── Where things live ─────────────────────────────────────────────────────────

def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


def config_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "backlinker" / "config.toml"


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "backlinker"


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / "backlinker"


def obsidian_registry_paths() -> list[Path]:
    """Where the Obsidian app keeps its list of vaults, per platform."""
    home = Path.home()
    if sys.platform == "darwin":
        return [home / "Library/Application Support/obsidian/obsidian.json"]
    if sys.platform == "win32":
        return [Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "obsidian/obsidian.json"]
    return [
        _xdg("XDG_CONFIG_HOME", ".config") / "obsidian/obsidian.json",
        home / ".var/app/md.obsidian.Obsidian/config/obsidian/obsidian.json",  # Flatpak
        home / "snap/obsidian/current/.config/obsidian/obsidian.json",
    ]


def discover_vaults() -> list[Path]:
    """Vaults Obsidian knows about, the open one first, then most recently used."""
    found = []
    for registry in obsidian_registry_paths():
        try:
            vaults = json.loads(registry.read_text(encoding="utf-8")).get("vaults", {})
        except (OSError, ValueError):
            continue
        for v in vaults.values():
            if isinstance(v, dict) and v.get("path") and Path(v["path"]).is_dir():
                found.append((not v.get("open"), -v.get("ts", 0), Path(v["path"])))
    return [p for *_, p in sorted(found)]


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class VaultSettings:
    """Per-vault settings in config.toml. Every key is optional."""
    path: str = ""
    heading: str = ""               # daily-note heading to capture under, e.g. "## Log"; "" = end of note
    time_prefix: bool = True        # "- 14:32 text"
    notes_heading: str = "## Notes"  # where --to adds a line in a note
    inbox: str = "Inbox.md"         # note that `bl triage` empties
    due_format: str = "tasks"       # "tasks" (📅 2026-10-09) or "dataview" ([due:: 2026-10-09])
    people_folders: list[str] = field(default_factory=lambda: ["People"])
    exclude: list[str] = field(default_factory=list)  # folders never indexed
    ignore: list[str] = field(default_factory=list)   # names never linked


SETTING_NAMES = [f.name for f in fields(VaultSettings) if f.name != "path"]


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        return {"vaults": {}}
    try:
        cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise VaultError(f"{path} is not valid TOML: {e}") from e
    cfg.setdefault("vaults", {})
    return cfg


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(v, ensure_ascii=False)  # a JSON string is a valid TOML basic string


def save_config(cfg: dict) -> Path:
    lines = ["# backlinker config: https://github.com/owen-alderson/backlinker#configuration"]
    if cfg.get("default"):
        lines.append(f"default = {_toml_value(cfg['default'])}")
    for name, table in cfg.get("vaults", {}).items():
        lines += ["", f"[vaults.{_toml_value(name)}]"]
        lines += [f"{k} = {_toml_value(v)}" for k, v in table.items()]
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def coerce_setting(key: str, raw: str):
    """Turn a `bl config KEY VALUE` string into the right type."""
    if key not in SETTING_NAMES:
        raise VaultError(f"unknown setting {key!r}; choose from: {', '.join(SETTING_NAMES)}")
    default = getattr(VaultSettings(), key)
    if isinstance(default, bool):
        if raw.lower() not in ("true", "false", "yes", "no", "on", "off"):
            raise VaultError(f"{key} must be true or false")
        return raw.lower() in ("true", "yes", "on")
    if isinstance(default, list):
        return [x.strip() for x in raw.split(",") if x.strip()]
    if key == "due_format" and raw not in ("tasks", "dataview"):
        raise VaultError("due_format must be tasks or dataview")
    return raw


# ── Vault ─────────────────────────────────────────────────────────────────────

@dataclass
class DailyNotes:
    folder: str = ""
    format: str = "YYYY-MM-DD"
    template: str = ""


@dataclass
class Vault:
    root: Path
    name: str
    settings: VaultSettings

    def _obsidian_json(self, rel: str) -> dict:
        try:
            data = json.loads((self.root / ".obsidian" / rel).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def daily_notes(self) -> DailyNotes:
        """Daily-note settings exactly as Obsidian uses them (Periodic Notes wins if enabled)."""
        periodic = self._obsidian_json("plugins/periodic-notes/data.json").get("daily") or {}
        enabled = "periodic-notes" in self._enabled_community_plugins()
        src = periodic if enabled and periodic.get("enabled") else self._obsidian_json("daily-notes.json")
        return DailyNotes(
            folder=(src.get("folder") or "").strip("/"),
            format=src.get("format") or "YYYY-MM-DD",
            template=(src.get("template") or "").strip("/"),
        )

    def templates(self) -> dict:
        t = self._obsidian_json("templates.json")
        return {"folder": (t.get("folder") or "").strip("/"),
                "date": t.get("dateFormat") or "YYYY-MM-DD", "time": t.get("timeFormat") or "HH:mm"}

    def _enabled_community_plugins(self) -> list:
        try:
            return json.loads((self.root / ".obsidian/community-plugins.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def note_path(self, rel: str) -> Path:
        """A vault-relative note path; refuses anything that escapes the vault."""
        rel = rel if rel.endswith(".md") else rel + ".md"
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise VaultError(f"{rel!r} is outside the vault")
        return path


def _v1_vault() -> Path | None:
    """obsidian-quick-add v1 kept its vault in ~/.config/obsidian-quick-add/config.json."""
    try:
        old = json.loads((Path.home() / ".config/obsidian-quick-add/config.json").read_text())
        return Path(old["vault"]).expanduser()
    except (OSError, ValueError, KeyError, TypeError):
        return None


def resolve_vault(choice: str | None = None) -> Vault:
    """Pick the vault: --vault (name or path), $BACKLINKER_VAULT, config default, then Obsidian's open vault."""
    cfg = load_config()
    choice = choice or os.environ.get("BACKLINKER_VAULT") or cfg.get("default")
    tables = cfg["vaults"]

    if choice:
        if choice in tables:
            table = tables[choice]
            root = Path(table.get("path") or "").expanduser()
        else:
            root = Path(choice).expanduser()
            table = next((t for t in tables.values() if Path(t.get("path", "")).expanduser() == root), {})
        if not root.is_dir():
            raise VaultError(f"vault not found: {choice} (run `bl init` to pick one)")
    else:
        candidates = discover_vaults() or [p for p in [_v1_vault()] if p and p.is_dir()]
        if not candidates:
            raise VaultError("no Obsidian vault found; run `bl init /path/to/vault`")
        root, table = candidates[0], {}

    known = {f.name for f in fields(VaultSettings)}
    settings = VaultSettings(**{k: v for k, v in table.items() if k in known})
    settings.path = str(root)
    return Vault(root=root, name=root.name, settings=settings)
