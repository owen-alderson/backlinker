from datetime import date, datetime

import pytest

from backlinker import journal
from backlinker.capture import apply, plan_capture, plan_link
from backlinker.notes import NoteNotFound
from conftest import NOW, read


def cap(vault, text, **kw):
    c = plan_capture(vault, text, now=NOW, **kw)
    apply(c, text)
    return c


def test_new_daily_note_from_template_with_link(demo):
    c = cap(demo, "coffee with Maya about Lumen")
    assert read(demo, "Daily/2026-10-07.md") == (
        "---\ndate: 2026-10-07\ntags: [daily]\n---\n# Wednesday, October 7th\n\n## Log\n"
        "- 14:32 coffee with [[Maya Chen|Maya]] about [[Lumen Labs|Lumen]]\n")
    assert c.links == ["Maya Chen", "Lumen Labs"] and c.op_id


def test_existing_daily_note_appends_under_heading(demo):
    cap(demo, "follow-up with Jonas", day=date(2026, 10, 6))
    text = read(demo, "Daily/2026-10-06.md")
    assert text.endswith("## Log\n- 09:10 kickoff for [[Harbor Launch]]\n- follow-up with [[Jonas Weber|Jonas]]\n")


def test_time_prefix_only_for_today_and_can_be_off(demo):
    cap(demo, "a", day=date(2026, 10, 5))
    assert read(demo, "Daily/2026-10-05.md").endswith("- a\n")
    demo.settings.time_prefix = False
    cap(demo, "b")
    assert read(demo, "Daily/2026-10-07.md").endswith("- b\n")


def test_task_with_due_date_tasks_and_dataview(demo):
    c = cap(demo, "send Jonas the deck fri", task=True)
    assert read(demo, "Daily/2026-10-07.md").endswith("- [ ] send [[Jonas Weber|Jonas]] the deck 📅 2026-10-09\n")
    assert c.due == ["2026-10-09"]
    demo.settings.due_format = "dataview"
    cap(demo, "todo: call Priya tomorrow")
    assert read(demo, "Daily/2026-10-07.md").endswith("- [ ] call [[Priya Raman|Priya]] [due:: 2026-10-08]\n")


def test_task_prefixes_are_detected(demo):
    cap(demo, "[ ] one\n- [ ] two\n[] three\nTODO four")
    assert read(demo, "Daily/2026-10-07.md").endswith("- [ ] one\n- [ ] two\n- [ ] three\n- [ ] four\n")


def test_multiline_input_one_entry_per_line_bullets_stripped(demo):
    cap(demo, "- first with Maya\n\n* second with Maya\n1. third\n")
    assert read(demo, "Daily/2026-10-07.md").endswith(
        "- 14:32 first with [[Maya Chen|Maya]]\n- 14:32 second with [[Maya Chen|Maya]]\n- 14:32 third\n")


def test_no_link(demo):
    cap(demo, "Maya", link=False)
    assert read(demo, "Daily/2026-10-07.md").endswith("- 14:32 Maya\n")


def test_ambiguous_names_reported_not_linked(demo):
    c = cap(demo, "lunch with Sam")
    assert c.ambiguous == [{"text": "Sam", "candidates": ["Sam Okafor", "Sam Patel"]}]
    assert read(demo, "Daily/2026-10-07.md").endswith("- 14:32 lunch with Sam\n")


def test_to_note_adds_dated_line_and_skips_self_link(demo):
    c = cap(demo, "Priya says Northwind fees are up", to=["Priya"])
    assert read(demo, "People/Priya Raman.md").endswith(
        "\n## Notes\n- [[2026-10-07]] Priya says [[Northwind Capital|Northwind]] fees are up\n")
    assert "[[Priya Raman|Priya]] says" in read(demo, "Daily/2026-10-07.md")
    assert set(c.lines) == {"Daily/2026-10-07.md", "People/Priya Raman.md"}


def test_to_note_appends_to_existing_section(demo):
    cap(demo, "warm intro to Maya", to=["Jonas Weber"])
    assert "## Notes\n- [[2026-10-01]] intro from Maya\n- [[2026-10-07]] warm intro to [[Maya Chen|Maya]]\n" \
        in read(demo, "People/Jonas Weber.md")


def test_task_with_to_lives_only_in_that_note(demo):
    cap(demo, "send Maya the term sheet fri", task=True, to=["Harbor"])
    assert read(demo, "Projects/Harbor Launch.md").endswith(
        "- [ ] send [[Maya Chen|Maya]] the term sheet 📅 2026-10-09\n")
    assert not (demo.root / "Daily/2026-10-07.md").exists()


def test_unknown_to_note_fails_before_writing(demo):
    with pytest.raises(NoteNotFound):
        plan_capture(demo, "x", to=["Nobody Here"], now=NOW)
    assert not (demo.root / "Daily/2026-10-07.md").exists()


def test_plan_writes_nothing_and_diff_shows_new_file(demo):
    c = plan_capture(demo, "Maya", now=NOW)
    assert not (demo.root / "Daily/2026-10-07.md").exists()
    diff = c.edits[0].diff(demo.root)
    assert diff.startswith("--- /dev/null\n+++ Daily/2026-10-07.md") and "+- 14:32 [[Maya Chen|Maya]]" in diff


def test_one_undo_reverts_every_file(demo):
    before = read(demo, "People/Jonas Weber.md")
    cap(demo, "pitch went well", to=["Jonas"])
    journal.undo(demo.root)
    assert read(demo, "People/Jonas Weber.md") == before
    assert not (demo.root / "Daily/2026-10-07.md").exists()


def test_crlf_daily_note_stays_crlf(make_vault):
    v = make_vault({"2026-10-07.md": "# Day\r\n- a\r\n", "Maya Chen.md": ""}, people_folders=[])
    cap(v, "b")
    assert (v.root / "2026-10-07.md").read_bytes() == b"# Day\r\n- a\r\n- 14:32 b\r\n"


def test_default_vault_without_settings(make_vault):
    v = make_vault({"People/Ann Lee.md": ""})
    cap(v, "Ann called")
    assert read(v, "2026-10-07.md") == "- 14:32 [[Ann Lee|Ann]] called\n"


def test_daily_folder_from_format_and_missing_template(make_vault):
    v = make_vault({".obsidian/daily-notes.json": {"folder": "J", "format": "YYYY/MM-MMM/DD ddd", "template": "nope"}})
    cap(v, "x")
    assert read(v, "J/2026/10-Oct/07 Wed.md") == "- 14:32 x\n"


def test_ignored_names_never_link(demo):
    demo.settings.ignore = ["Python"]
    cap(demo, "Python script")
    assert read(demo, "Daily/2026-10-07.md").endswith("- 14:32 Python script\n")


def test_conflict_while_writing_writes_nothing_after_it(demo, monkeypatch):
    c = plan_capture(demo, "x", to=["Jonas"], now=NOW)
    (demo.root / "People/Jonas Weber.md").write_text("changed meanwhile")
    from backlinker import safewrite
    with pytest.raises(safewrite.Conflict):
        apply(c, "x")
    assert read(demo, "People/Jonas Weber.md") == "changed meanwhile"
    journal.undo(demo.root)  # whatever was written before the conflict can be undone
    assert not (demo.root / "Daily/2026-10-07.md").exists()


def test_plan_link_retro_links_a_note(demo):
    c = plan_link(demo, "Priya")
    assert c.edits[0].after.endswith(
        "Runs [[Market Making|market making]] at [[Northwind Capital|Northwind]].\n")
    apply(c, "link")
    assert plan_link(demo, "Priya").edits == []  # nothing left to link


def test_plan_link_by_path_and_skips_self(demo):
    (demo.root / "People/Maya Chen.md").write_text("# Maya Chen\nMaya met Jonas.\n")
    c = plan_link(demo, str(demo.root / "People/Maya Chen.md"))
    assert c.edits[0].after == "# Maya Chen\nMaya met [[Jonas Weber|Jonas]].\n"
