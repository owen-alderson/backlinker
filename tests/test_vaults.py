import json
import tomllib

import pytest

from backlinker import vaults
from backlinker.vaults import (VaultError, coerce_setting, config_path, discover_vaults, load_config,
                               resolve_vault, save_config)


def test_discover_orders_open_vault_first_then_recent(tmp_path, registry):
    a, b, c = (tmp_path / n for n in "abc")
    for p in (a, b, c):
        p.mkdir()
    registry({a: {"ts": 1}, b: {"ts": 5}, c: {"ts": 2, "open": True}, tmp_path / "gone": {"ts": 9}})
    assert discover_vaults() == [c, b, a]


def test_discover_tolerates_missing_or_broken_registry(tmp_path):
    assert discover_vaults() == []
    (tmp_path / "obsidian.json").write_text("{oops")
    assert discover_vaults() == []


def test_registry_paths_per_platform(monkeypatch):
    monkeypatch.undo()  # use the real function
    for platform, needle in (("darwin", "Library/Application Support/obsidian"),
                             ("win32", "obsidian/obsidian.json"), ("linux", ".config/obsidian")):
        monkeypatch.setattr(vaults.sys, "platform", platform)
        assert any(needle in p.as_posix() for p in vaults.obsidian_registry_paths())


def test_config_round_trip_with_quotes_and_unicode(tmp_path):
    cfg = {"default": "Léa's \"vault\"", "vaults": {"Léa's \"vault\"": {
        "path": str(tmp_path), "heading": "## Log", "time_prefix": False, "ignore": ["Home", "To-do"]}}}
    save_config(cfg)
    assert tomllib.loads(config_path().read_text(encoding="utf-8")) == cfg
    assert load_config() == cfg


def test_bad_toml_is_a_clear_error():
    config_path().parent.mkdir(parents=True)
    config_path().write_text("default = [")
    with pytest.raises(VaultError, match="not valid TOML"):
        load_config()


@pytest.mark.parametrize("key,raw,expect", [
    ("time_prefix", "no", False), ("time_prefix", "TRUE", True), ("ignore", "Home, Inbox ,", ["Home", "Inbox"]),
    ("heading", "## Log", "## Log"), ("due_format", "dataview", "dataview"),
])
def test_coerce_setting(key, raw, expect):
    assert coerce_setting(key, raw) == expect


@pytest.mark.parametrize("key,raw", [("time_prefix", "maybe"), ("due_format", "emoji"), ("nope", "x"), ("path", "/x")])
def test_coerce_setting_rejects(key, raw):
    with pytest.raises(VaultError):
        coerce_setting(key, raw)


def test_resolve_precedence(tmp_path, registry, monkeypatch):
    open_v, cfg_v, env_v, flag_v = (tmp_path / n for n in ("open", "cfg", "env", "flag"))
    for p in (open_v, cfg_v, env_v, flag_v):
        p.mkdir()
    registry({open_v: {"open": True}})
    assert resolve_vault().root == open_v
    save_config({"default": "cfg", "vaults": {"cfg": {"path": str(cfg_v), "heading": "## Log"}}})
    v = resolve_vault()
    assert v.root == cfg_v and v.settings.heading == "## Log"
    monkeypatch.setenv("BACKLINKER_VAULT", str(env_v))
    assert resolve_vault().root == env_v
    assert resolve_vault(str(flag_v)).root == flag_v


def test_resolve_by_path_picks_up_that_vaults_settings(tmp_path):
    (tmp_path / "v").mkdir()
    save_config({"vaults": {"mine": {"path": str(tmp_path / "v"), "time_prefix": False}}})
    assert resolve_vault(str(tmp_path / "v")).settings.time_prefix is False


def test_resolve_errors(tmp_path):
    with pytest.raises(VaultError, match="no Obsidian vault found"):
        resolve_vault()
    with pytest.raises(VaultError, match="vault not found"):
        resolve_vault(str(tmp_path / "missing"))


def test_v1_config_is_used_when_nothing_else(tmp_path):
    old = tmp_path / "home/.config/obsidian-quick-add/config.json"
    old.parent.mkdir(parents=True)
    (tmp_path / "oldvault").mkdir()
    old.write_text(json.dumps({"vault": str(tmp_path / "oldvault")}))
    assert resolve_vault().root == tmp_path / "oldvault"


def test_daily_settings_default_core_and_periodic(make_vault):
    v = make_vault({})
    assert (v.daily_notes().folder, v.daily_notes().format) == ("", "YYYY-MM-DD")
    v = make_vault({".obsidian/daily-notes.json": {"folder": "/Journal/", "format": "YYYY/MM/DD", "template": "T/D"}})
    dn = v.daily_notes()
    assert (dn.folder, dn.format, dn.template) == ("Journal", "YYYY/MM/DD", "T/D")
    (v.root / ".obsidian/plugins/periodic-notes").mkdir(parents=True)
    (v.root / ".obsidian/plugins/periodic-notes/data.json").write_text(
        json.dumps({"daily": {"enabled": True, "folder": "Periodic", "format": "DD-MM-YYYY"}}))
    assert v.daily_notes().folder == "Journal"  # plugin installed but not enabled
    (v.root / ".obsidian/community-plugins.json").write_text('["periodic-notes"]')
    assert (v.daily_notes().folder, v.daily_notes().format) == ("Periodic", "DD-MM-YYYY")


def test_note_path_cannot_escape_vault(make_vault):
    v = make_vault({})
    assert v.note_path("a/b").name == "b.md"
    with pytest.raises(VaultError):
        v.note_path("../outside")
