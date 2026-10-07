import io
import json
import re

import pytest

from backlinker.cli import run
from backlinker.vaults import load_config, save_config


@pytest.fixture
def vault(demo):
    save_config({"default": "demo", "vaults": {"demo": {"path": str(demo.root), "heading": "## Log"}}})
    return demo


def daily(v):
    import datetime
    return (v.root / f"Daily/{datetime.date.today()}.md")


def test_capture_is_the_default_command(vault, capsys):
    assert run(["coffee", "with", "Maya"]) == 0
    out = capsys.readouterr().out
    assert "[[Maya Chen|Maya]]" in out and "✓ linked Maya Chen" in out and "undo: bl undo" in out
    assert re.search(r"- \d\d:\d\d coffee with \[\[Maya Chen\|Maya\]\]\n$", daily(vault).read_text())


def test_dry_run_prints_diff_and_writes_nothing(vault, capsys):
    assert run(["-n", "Maya"]) == 0
    out = capsys.readouterr().out
    assert "+++ Daily/" in out and "dry run: nothing was written" in out
    assert not daily(vault).exists()


def test_json_output(vault, capsys):
    run(["--json", "-t", "ask Sam about fees tomorrow"])
    data = json.loads(capsys.readouterr().out)
    assert data["ambiguous"][0]["candidates"] == ["Sam Okafor", "Sam Patel"]
    assert len(data["due"]) == 1 and data["undo_id"] and data["dry_run"] is False


def test_stdin(vault, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("one with Maya\ntwo with Jonas\n"))
    assert run(["-"]) == 0
    text = daily(vault).read_text()
    assert "one with [[Maya Chen|Maya]]" in text and "two with [[Jonas Weber|Jonas]]" in text


def test_empty_stdin(vault, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("  \n"))
    assert run([]) == 2


def test_date_and_to_flags(vault, capsys):
    assert run(["--date", "2026-10-06", "--to", "Jonas", "pitch prep"]) == 0
    assert "- pitch prep\n" in (vault.root / "Daily/2026-10-06.md").read_text()
    assert "- [[2026-10-06]] pitch prep\n" in (vault.root / "People/Jonas Weber.md").read_text()


def test_errors_exit_1_with_message(vault, capsys):
    assert run(["--to", "Nobody", "x"]) == 1
    assert "no note called 'Nobody'" in capsys.readouterr().err
    assert run(["--date", "10/9", "x"]) == 1
    assert "can't read '10/9' as a date" in capsys.readouterr().err
    assert run(["--vault", "/no/such/vault", "x"]) == 1


def test_heading_override(vault, capsys):
    run(["--heading", "## Ideas", "-n", "x"])
    assert "+## Ideas" in capsys.readouterr().out


def test_undo(vault, capsys):
    run(["Maya"])
    capsys.readouterr()
    assert run(["undo"]) == 0
    assert "undid: Maya" in capsys.readouterr().out and not daily(vault).exists()
    assert run(["undo"]) == 1 and "nothing to undo" in capsys.readouterr().err


def test_link_command(vault, capsys):
    assert run(["link", "Priya", "-n"]) == 0
    assert "+Runs [[Market Making|market making]]" in capsys.readouterr().out
    assert run(["link", "Priya"]) == 0
    assert "[[Northwind Capital|Northwind]]" in (vault.root / "People/Priya Raman.md").read_text()
    assert run(["link", "Priya"]) == 0 and "nothing to change" in capsys.readouterr().out


def test_init_with_path_and_from_registry(tmp_path, demo, registry, capsys):
    assert run(["init", str(demo.root)]) == 0
    out = capsys.readouterr().out
    assert "daily notes: Daily/YYYY-MM-DD.md, template Templates/Daily" in out and "6 of them people" in out
    assert load_config()["default"] == "demo"
    other = tmp_path / "Other Vault"
    other.mkdir()
    registry({other: {"open": True}, demo.root: {"ts": 1}})
    assert run(["init"]) == 0  # not a terminal: takes the open vault
    assert load_config()["default"] == "Other Vault" and "demo" in load_config()["vaults"]


def test_init_without_any_vault(capsys):
    assert run(["init"]) == 1


def test_config_show_set_get(vault, capsys):
    assert run(["config", "time_prefix", "false"]) == 0
    assert load_config()["vaults"]["demo"]["time_prefix"] is False
    capsys.readouterr()
    run(["config", "heading"])
    assert capsys.readouterr().out.strip() == "## Log"
    run(["config"])
    out = capsys.readouterr().out
    assert "time_prefix = False" in out and "inbox = 'Inbox.md'   (default)" in out
    assert run(["config", "due_format", "emoji"]) == 1


def test_version_and_help(capsys):
    with pytest.raises(SystemExit):
        run(["--version"])
    assert "backlinker 2.0.0" in capsys.readouterr().out


def test_triage_needs_a_terminal_or_all(vault, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert run(["triage"]) == 2
    assert run(["triage", "--all"]) == 0
    assert "3 filed" in capsys.readouterr().out


def test_mcp_without_package_explains(vault, capsys, monkeypatch):
    import builtins
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__",
                        lambda name, *a, **k: (_ for _ in ()).throw(ImportError()) if name.endswith("mcp_server")
                        else real(name, *a, **k))
    assert run(["mcp"]) == 1 and "backlinker[mcp]" in capsys.readouterr().err
