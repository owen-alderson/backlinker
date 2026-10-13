import pytest

from backlinker import journal
from backlinker.capture import apply, plan_capture
from backlinker.dossier import gather, plan_add, plan_dossier, set_block
from backlinker.notes import AmbiguousNote, NoteNotFound, insert_lines

from conftest import NOW, read

PERSON = "---\ntags: [person]\n---\n# Ann Lee\n\nMet at the fair.\n\n## Notes\n- likes tea\n"
FILES = {
    ".obsidian/daily-notes.json": {"folder": "Daily", "format": "YYYY-MM-DD"},
    "People/Ann Lee.md": PERSON,
    "People/Bo Chen.md": "---\ntags: [person]\n---\n# Bo Chen\n",
    "Companies/Acme.md": "# Acme\n",
    "Daily/2026-10-01.md": "- call with [[Ann Lee]] and [[Acme]] about the pilot\n"
                           "- [ ] send Ann the deck 📅 2026-10-03\n- lunch alone\n",
    "Daily/2026-10-05.md": "- Ann Lee wants weekly updates\n```\nAnn Lee in code\n```\n",
    "Projects/Pilot.md": "---\naliases: [Ann Lee project]\n---\n# Pilot\n2026-09-20 — kickoff with [[Ann Lee]]\n"
                         "- [x] Ann signed\n- [[Ann Lee]] and [[Bo Chen]] own the rollout\n",
    "Notes/Report.md": "Annual report, nothing about people\n",
}


@pytest.fixture
def vault(make_vault):
    return make_vault(FILES)


def test_gathers_linked_and_unlinked_mentions(vault):
    d = gather(vault, "People/Ann Lee.md")
    got = [(m.source, m.line, m.day, m.linked, m.task) for m in d.mentions]
    assert sorted(got) == [
        ("Daily/2026-10-01.md", 1, "2026-10-01", True, None),
        ("Daily/2026-10-01.md", 2, "2026-10-01", False, "open"),     # unique first name, unlinked
        ("Daily/2026-10-05.md", 1, "2026-10-05", False, None),       # the code block is skipped
        ("Projects/Pilot.md", 5, "2026-09-20", True, None),          # date at the start of the line
        ("Projects/Pilot.md", 6, None, False, "done"),
        ("Projects/Pilot.md", 7, None, True, None),
    ]
    assert d.mentioned_with() == [("Acme", 1), ("Bo Chen", 1)]
    assert d.unlinked_in == ["Daily/2026-10-01.md", "Daily/2026-10-05.md", "Projects/Pilot.md"]
    assert [m.text for m in d.open_tasks] == ["send Ann the deck 📅 2026-10-03"]


def test_whole_words_and_ambiguous_first_names_are_not_mentions(make_vault):
    v = make_vault({**FILES, "People/Ann Park.md": "---\ntags: [person]\n---\n"})
    d = gather(v, "People/Ann Lee.md")
    assert not any(m.source == "Notes/Report.md" for m in d.mentions)          # "Annual"
    assert not any("send Ann" in m.text or m.text == "Ann signed" for m in d.mentions)  # two Anns now


def test_block_written_at_the_end_and_rebuilds_cleanly(vault):
    cap, d = plan_dossier(vault, "Ann")
    apply(cap, "dossier")
    text = read(vault, "People/Ann Lee.md")
    assert text.startswith(PERSON.rstrip("\n") + "\n\n<!-- backlinker:dossier")
    assert text.endswith("<!-- /backlinker:dossier -->\n")
    assert "**6 mentions in 3 notes** · first 2026-09-20 · last 2026-10-05" in text
    assert "**Open tasks**\n- send Ann the deck 📅 2026-10-03 ([[2026-10-01]])" in text
    assert "- [ ]" not in text.split("<!--", 1)[1]          # no duplicate tasks for the Tasks plugin
    assert "**Mentioned with** [[Acme]] (1) · [[Bo Chen]] (1)" in text
    assert "- [[2026-10-05]]: Ann Lee wants weekly updates" in text
    assert "- [[2026-10-01]] (2): call with Ann Lee and Acme about the pilot" in text
    assert "- 2026-09-20 · [[Pilot]]: 2026-09-20 — kickoff with Ann Lee" in text
    assert "**Also in** [[Pilot]] (2)" in text
    assert plan_dossier(vault, "Ann")[0].edits == []       # same vault, same block

    journal.undo(vault.root)
    assert read(vault, "People/Ann Lee.md") == PERSON


def test_blocks_are_not_mentions(vault):
    apply(plan_dossier(vault, "Ann Lee")[0], "dossier")    # Ann's block mentions Bo Chen
    assert [m.source for m in gather(vault, "People/Bo Chen.md").mentions] == ["Projects/Pilot.md"]


def test_no_mentions_writes_nothing(make_vault):
    v = make_vault({"People/Cy Ng.md": "# Cy Ng\n"}, people_folders=["People"])
    cap, d = plan_dossier(v, "Cy Ng")
    assert d.mentions == [] and cap.edits == []


def test_set_block_replaces_in_place_and_keeps_text_after_it():
    old = "# A\n\n<!-- backlinker:dossier: x -->\nold\n<!-- /backlinker:dossier -->\n\n## Later\nmine\n"
    new = set_block(old, "<!-- backlinker:dossier: x -->\nnew\n<!-- /backlinker:dossier -->")
    assert new == old.replace("old", "new")
    with pytest.raises(ValueError, match="no end marker"):
        set_block("<!-- backlinker:dossier: x -->\nold\n", "b")


def test_crlf_note_keeps_its_line_endings(make_vault):
    v = make_vault({**FILES, "People/Ann Lee.md": PERSON.replace("\n", "\r\n")})
    apply(plan_dossier(v, "Ann Lee")[0], "dossier")
    text = (v.root / "People/Ann Lee.md").read_bytes().decode()
    assert "\r\n<!-- /backlinker:dossier -->\r\n" in text and "\n" not in text.replace("\r\n", "")


def test_inserts_land_above_the_block(vault):
    apply(plan_dossier(vault, "Ann Lee")[0], "dossier")
    apply(plan_capture(vault, "prefers mornings", to=["Ann Lee"], now=NOW), "x")
    text = read(vault, "People/Ann Lee.md")
    assert "- likes tea\n- [[2026-10-07]] prefers mornings\n\n<!-- backlinker:dossier" in text
    assert insert_lines("# A\n\n<!-- backlinker:dossier -->\nb\n<!-- /backlinker:dossier -->\n", ["- x"], "## New") \
        == "# A\n\n## New\n- x\n\n<!-- backlinker:dossier -->\nb\n<!-- /backlinker:dossier -->\n"


def test_create_starts_a_person_note_where_people_live(make_vault):
    v = make_vault({**FILES, "Daily/2026-10-06.md": "- coffee with Dee Moss\n"})
    with pytest.raises(NoteNotFound):
        plan_dossier(v, "Dee Moss")
    cap, d = plan_dossier(v, "Dee Moss", create=True)
    apply(cap, "dossier")
    text = read(v, "People/Dee Moss.md")
    assert text.startswith("---\ntags: [person]\n---\n# Dee Moss\n\n## Overview\n")
    assert "- [[2026-10-06]]: coffee with Dee Moss" in text


def test_create_never_guesses_between_notes(make_vault):
    v = make_vault({"People/Sam A.md": "---\naliases: [Sam]\n---\n", "People/Sam B.md": "---\naliases: [Sam]\n---\n"})
    with pytest.raises(AmbiguousNote):
        plan_dossier(v, "Sam", create=True)


def test_other_daily_note_formats(make_vault):
    v = make_vault({".obsidian/daily-notes.json": {"folder": "Journal", "format": "dddd, MMMM Do YYYY"},
                    "People/Ann Lee.md": PERSON,
                    "Journal/Monday, October 12th 2026.md": "- saw Ann Lee\n",
                    "Journal/Tuesday, October 12th 2026.md": "- Ann Lee again\n"})   # wrong weekday: not a date
    days = {m.source: m.day for m in gather(v, "People/Ann Lee.md").mentions}
    assert days == {"Journal/Monday, October 12th 2026.md": "2026-10-12", "Journal/Tuesday, October 12th 2026.md": None}


def test_add_facts_with_sources(vault):
    apply(plan_dossier(vault, "Ann Lee")[0], "dossier")
    cap = plan_add(vault, "Ann Lee", "Key Facts", ["CTO at Acme, works with Bo Chen", "- Ann Lee lives in Lisbon"],
                   ["https://acme.example/team", " "])
    apply(cap, "add")
    text = read(vault, "People/Ann Lee.md")
    assert "## Key Facts\n- CTO at [[Acme]], works with [[Bo Chen]]\n- Ann Lee lives in Lisbon\n" in text
    assert "## Sources\n- https://acme.example/team\n\n<!-- backlinker:dossier" in text
    again = plan_add(vault, "Ann Lee", "Background", ["Studied in Porto"], ["https://acme.example/team"])
    assert again.lines["People/Ann Lee.md"] == ["- Studied in Porto"]       # source already cited


def test_add_refuses_unsourced_facts_and_the_generated_section(vault):
    with pytest.raises(ValueError, match="source"):
        plan_add(vault, "Ann Lee", "Key Facts", ["CTO"], [])
    with pytest.raises(ValueError, match="rebuilt"):
        plan_add(vault, "Ann Lee", "From the vault", ["x"], ["https://a.example"])
    with pytest.raises(NoteNotFound):
        plan_add(vault, "Nobody Here", "Key Facts", ["x"], ["https://a.example"])


def test_bl_link_leaves_the_block_alone(vault):
    from backlinker.capture import plan_link
    apply(plan_dossier(vault, "Ann Lee")[0], "dossier")
    before = read(vault, "People/Ann Lee.md")
    head, block = before.split("<!-- backlinker:dossier", 1)
    (vault.root / "People/Ann Lee.md").write_text(head.replace("Met at the fair.", "Met Bo Chen at the fair.")
                                                   + "<!-- backlinker:dossier" + block)
    apply(plan_link(vault, "Ann Lee"), "link")
    after = read(vault, "People/Ann Lee.md")
    assert "Met [[Bo Chen]] at the fair." in after
    assert after.split("<!-- backlinker:dossier", 1)[1] == block      # "Acme" in the block stays plain
