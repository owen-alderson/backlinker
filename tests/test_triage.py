from datetime import date, time

import pytest

from backlinker import journal, safewrite
from backlinker.triage import items, triage
from conftest import NOW, read


def test_items_parsing():
    text = ("---\ntags: [inbox]\n---\n# Inbox\n\n- 2026-10-06 18:40 Jonas call\n"
            "- [ ] buy gift\n- [x] done already\n  - nested detail\nplain line\n\tindented more\n"
            "- 2026-10-05 - dated only\n- 2026-13-45 not a date\n")
    got = [(i.text, i.day, i.at) for i in items(text)]
    assert got == [
        ("Jonas call", date(2026, 10, 6), time(18, 40)),
        ("[ ] buy gift", None, None),
        ("plain line indented more", None, None),
        ("dated only", date(2026, 10, 5), None),
        ("2026-13-45 not a date", None, None),
    ]


def scripted(*answers):
    answers = list(answers)
    return lambda prompt: answers.pop(0)


def run(vault, *answers, **kw):
    said = []
    counts = triage(vault, ask=scripted(*answers), say=said.append, now=NOW, **kw)
    return counts, "\n".join(said)


def test_file_task_delete(demo):
    counts, said = run(demo, "", "t", "d")
    assert counts == {"filed": 2, "deleted": 1, "skipped": 0}
    # first line keeps its own date and time
    assert read(demo, "Daily/2026-10-06.md").endswith(
        "- 18:40 [[Jonas Weber|Jonas]] thinks [[Northwind Capital|Northwind]] will lead the round\n")
    assert read(demo, "Daily/2026-10-07.md").endswith(
        "- [ ] ask [[Priya Raman|Priya]] about [[ETF]] [[Market Making|market making]] fees 📅 2026-10-09\n")
    assert read(demo, "Inbox.md") == "# Inbox\n\n"
    assert "3 line(s) in Inbox.md" in said


def test_skip_quit_and_into_a_note(demo):
    counts, said = run(demo, "s", "n", "", "n", "Lea Dubois", "n", "Léa", "q")
    assert counts == {"filed": 1, "deleted": 0, "skipped": 1}
    assert "no note called 'Lea Dubois'; did you mean 'Léa Dubois'?" in said
    assert "- [[2026-10-07]] ask [[Priya Raman|Priya]]" in read(demo, "People/Léa Dubois.md")
    inbox = read(demo, "Inbox.md")
    assert "Jonas thinks" in inbox and "ask Priya" not in inbox and "birthday gift" in inbox


def test_unknown_key_shows_help(demo):
    _, said = run(demo, "?", "q")
    assert said.count("[enter] file") >= 2


def test_file_all(demo):
    counts, _ = run(demo, file_all=True)
    assert counts["filed"] == 3 and read(demo, "Inbox.md") == "# Inbox\n\n"


def test_each_line_is_one_undo_step_including_the_inbox(demo):
    before = read(demo, "Inbox.md")
    run(demo, "", "q")
    journal.undo(demo.root)
    assert read(demo, "Inbox.md") == before
    assert read(demo, "Daily/2026-10-06.md").endswith("kickoff for [[Harbor Launch]]\n")


def test_line_is_never_lost_when_filing_fails(demo, monkeypatch):
    real = safewrite.write

    def failing(snap, text):
        if snap.path.name.startswith("2026"):
            raise OSError("disk full")
        return real(snap, text)

    monkeypatch.setattr(safewrite, "write", failing)
    counts, said = run(demo, "", "", "", )
    assert counts == {"filed": 0, "deleted": 0, "skipped": 3} and "disk full" in said
    assert read(demo, "Inbox.md").count("\n- ") == 3


def test_inbox_edited_during_triage_is_left_alone(demo):
    def ask(prompt):
        (demo.root / "Inbox.md").write_text("# Inbox\n\nrewritten on my phone\n")
        return ""
    said = []
    counts = triage(demo, ask=ask, say=said.append, now=NOW)
    assert "no longer in Inbox.md" in "\n".join(said)
    assert read(demo, "Inbox.md") == "# Inbox\n\nrewritten on my phone\n"
    assert not (demo.root / "Daily/2026-10-06.md").read_text().count("thinks")


def test_empty_or_missing_inbox(demo):
    (demo.root / "Inbox.md").unlink()
    counts, said = run(demo)
    assert counts["filed"] == 0 and "empty" in said


def test_custom_inbox_name_without_extension(demo):
    (demo.root / "Capture.md").write_text("- hello Maya\n")
    demo.settings.inbox = "Capture"
    counts, _ = run(demo, file_all=True)
    assert counts["filed"] == 1 and read(demo, "Capture.md") == ""
