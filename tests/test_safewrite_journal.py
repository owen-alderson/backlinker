import os

import pytest

from backlinker import journal, safewrite
from backlinker.journal import _inserted


def test_read_missing_and_crlf(tmp_path):
    assert safewrite.read(tmp_path / "x.md").text is None
    (tmp_path / "w.md").write_bytes(b"a\r\nb\r\n")
    snap = safewrite.read(tmp_path / "w.md")
    assert snap.text == "a\r\nb\r\n" and snap.newline == "\r\n"


def test_write_round_trips_bytes_exactly(tmp_path):
    p = tmp_path / "n.md"
    p.write_bytes("é\r\n".encode())
    snap = safewrite.read(p)
    safewrite.write(snap, snap.text + "ü\r\n")
    assert p.read_bytes() == "é\r\nü\r\n".encode()
    assert [f.name for f in tmp_path.iterdir()] == ["n.md"]  # no temp files left behind


def test_write_creates_folders(tmp_path):
    safewrite.write(safewrite.read(tmp_path / "a/b/c.md"), "x")
    assert (tmp_path / "a/b/c.md").read_text() == "x"


def test_write_refuses_if_file_changed(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("one")
    snap = safewrite.read(p)
    p.write_text("one, edited elsewhere")
    with pytest.raises(safewrite.Conflict):
        safewrite.write(snap, "two")
    assert p.read_text() == "one, edited elsewhere"


def test_write_refuses_if_file_appeared(tmp_path):
    snap = safewrite.read(tmp_path / "n.md")
    (tmp_path / "n.md").write_text("someone else")
    with pytest.raises(safewrite.Conflict):
        safewrite.write(snap, "mine")
    assert (tmp_path / "n.md").read_text() == "someone else"


def test_failed_write_leaves_original_and_no_temp(tmp_path, monkeypatch):
    p = tmp_path / "n.md"
    p.write_text("keep me")
    snap = safewrite.read(p)
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        safewrite.write(snap, "new")
    assert p.read_text() == "keep me" and [f.name for f in tmp_path.iterdir()] == ["n.md"]


@pytest.mark.parametrize("before,after,block", [
    ("a\nc\n", "a\nb\nc\n", "b\n"), ("", "x\n", "x\n"), ("a\n", "a\nb\n", "b\n"),
    ("a b", "a [[b]]", None), ("abc", "ab", None),
])
def test_inserted_block(before, after, block):
    assert _inserted(before, after) == block


def _op(tmp_path, before, after, name="n.md"):
    p = tmp_path / name
    if before is not None:
        p.write_text(before)
    safewrite.write(safewrite.read(p), after)
    return journal.record(tmp_path, "test", [(p, before, after)]), p


def test_undo_restores_exactly(tmp_path):
    _, p = _op(tmp_path, "a\n", "a\nb\n")
    assert journal.undo(tmp_path)["summary"] == "test"
    assert p.read_text() == "a\n"
    with pytest.raises(LookupError):
        journal.undo(tmp_path)


def test_undo_deletes_a_file_it_created(tmp_path):
    _, p = _op(tmp_path, None, "new\n")
    journal.undo(tmp_path)
    assert not p.exists()


def test_undo_keeps_later_edits_elsewhere_in_the_note(tmp_path):
    _, p = _op(tmp_path, "a\n", "a\nmine\n")
    p.write_text("top\na\nmine\nlater\n")
    journal.undo(tmp_path)
    assert p.read_text() == "top\na\nlater\n"


def test_undo_refuses_when_our_text_was_edited(tmp_path):
    _, p = _op(tmp_path, "a\n", "a\nmine\n")
    p.write_text("a\nmine, edited\n")
    with pytest.raises(safewrite.Conflict):
        journal.undo(tmp_path)
    assert p.read_text() == "a\nmine, edited\n"
    assert journal.last(tmp_path) is not None  # still undoable later


def test_undo_refuses_edited_file_it_created(tmp_path):
    _, p = _op(tmp_path, None, "new\n")
    p.write_text("new\nmore\n")
    with pytest.raises(safewrite.Conflict):
        journal.undo(tmp_path)
    assert p.exists()


def test_undo_is_all_or_nothing(tmp_path):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("a\n"), b.write_text("b\n")
    safewrite.write(safewrite.read(a), "a\n1\n")
    safewrite.write(safewrite.read(b), "b\n2\n")
    journal.record(tmp_path, "two files", [(a, "a\n", "a\n1\n"), (b, "b\n", "b\n2\n")])
    b.write_text("b\n2 edited\n")
    with pytest.raises(safewrite.Conflict):
        journal.undo(tmp_path)
    assert a.read_text() == "a\n1\n"


def test_undo_walks_back_and_is_per_vault(tmp_path):
    (tmp_path / "v1").mkdir(), (tmp_path / "v2").mkdir()
    _op(tmp_path / "v1", "", "1\n")
    _op(tmp_path / "v2", "", "x\n")
    p = tmp_path / "v1/n.md"
    safewrite.write(safewrite.read(p), "1\n2\n")
    journal.record(tmp_path / "v1", "second", [(p, "1\n", "1\n2\n")])
    assert journal.undo(tmp_path / "v1")["summary"] == "second"
    assert journal.undo(tmp_path / "v1")["summary"] == "test"
    assert p.read_text() == "" and (tmp_path / "v2/n.md").read_text() == "x\n"


def test_journal_keeps_only_recent_ops(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "KEEP", 3)
    for i in range(5):
        journal.record(tmp_path, f"op{i}", [])
    assert [o["summary"] for o in journal._load()] == ["op2", "op3", "op4"]


def test_journal_skips_corrupt_lines(tmp_path):
    journal.record(tmp_path, "ok", [])
    with journal._file().open("a") as f:
        f.write("{broken\n")
    assert journal.last(tmp_path)["summary"] == "ok"
