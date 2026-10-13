from datetime import date

import pytest

from backlinker import journal
from backlinker.capture import apply
from backlinker.guests import Guest, match, parse_line, plan_guests, read_guest_list, resolve_picks
from backlinker.index import scan

from conftest import read

TODAY = date(2026, 10, 13)
PEOPLE = {
    ".obsidian/daily-notes.json": {"folder": "Daily", "format": "YYYY-MM-DD"},
    "Atlas/People/Ann Lee.md": "---\ntags: [person]\naliases: [Annie Lee]\n---\n# Ann Lee\n\n## Notes\n- likes tea\n",
    "Atlas/People/Sam Okafor.md": "---\ntags: [person]\naliases: [Sam O]\n---\n",
    "Atlas/People/Sam O'Neil.md": "---\ntags: [person]\naliases: [Sam O]\n---\n",
    "Atlas/People/Jonas Weber.md": "---\ntags: [person]\n---\n",
    "Events/Founders Night.md": "# Founders Night\n",
    "Daily/2026-10-02.md": "- Dee Moss is raising a seed round\n",
}


@pytest.fixture
def vault(make_vault):
    return make_vault(PEOPLE, people_folders=["People"])


def test_parse_text_lines():
    assert parse_line("- Jane Doe - CEO, Acme") == Guest("Jane Doe", "CEO, Acme")
    assert parse_line("3. Omar Haddad (Lumen Labs)") == Guest("Omar Haddad", "Lumen Labs")
    assert parse_line("Li Wei, Partner at Northwind") == Guest("Li Wei", "Partner at Northwind")
    assert parse_line("- [ ] **Ann Lee**") == Guest("Ann Lee")
    assert parse_line("# Guests") is None and parse_line("   ") is None and parse_line("- 42") is None


def test_read_csv_with_first_and_last_columns(tmp_path):
    f = tmp_path / "luma.csv"
    f.write_text("﻿First Name,Last Name,Email,Company,Job Title\nJane,Doe,jane@acme.example,Acme,CEO\n,,,,\n"
                 "Omar,Haddad,,,\n")
    assert read_guest_list(f) == [
        Guest("Jane Doe", facts={"Title": "CEO", "Company": "Acme", "Email": "jane@acme.example"}),
        Guest("Omar Haddad")]


def test_read_csv_name_column_tsv_and_text(tmp_path):
    (tmp_path / "a.csv").write_text("Name,Organization\n\"Doe, Jane\",Acme\n")
    assert read_guest_list(tmp_path / "a.csv") == [Guest("Doe, Jane", facts={"Company": "Acme"})]
    (tmp_path / "b.tsv").write_text("Full Name\tRole\nLi Wei\tPartner\n")
    assert read_guest_list(tmp_path / "b.tsv") == [Guest("Li Wei", facts={"Title": "Partner"})]
    (tmp_path / "c.md").write_text("# Guests\n\n- Jane Doe — CEO\n- Li Wei\n")
    assert [g.name for g in read_guest_list(tmp_path / "c.md")] == ["Jane Doe", "Li Wei"]
    (tmp_path / "d.csv").write_text("Email,Company\nx@y.example,Acme\n")
    with pytest.raises(ValueError, match="no name column"):
        read_guest_list(tmp_path / "d.csv")


def test_match_known_alias_ambiguous_near_and_new(vault):
    got = match([Guest("ann lee"), Guest("Annie Lee"), Guest("Sam O"), Guest("Jonas K. Weber"), Guest("Dee Moss"),
                 Guest("Sam"), Guest("Omar")], scan(vault), ["People"])
    assert [(m.status, m.notes) for m in got] == [
        ("known", ["Atlas/People/Ann Lee.md"]),
        ("known", ["Atlas/People/Ann Lee.md"]),
        ("ambiguous", ["Atlas/People/Sam O'Neil.md", "Atlas/People/Sam Okafor.md"]),
        ("maybe", ["Atlas/People/Jonas Weber.md"]),
        ("new", []),
        ("maybe", ["Atlas/People/Sam O'Neil.md", "Atlas/People/Sam Okafor.md"]),   # a lone first name
        ("new", []),
    ]


def test_picks_by_full_or_unique_first_name(vault):
    ms = match([Guest("Jane Doe"), Guest("Jane Roe"), Guest("Omar Haddad")], scan(vault), ["People"])
    assert [m.guest.name for m in resolve_picks(ms, ["omar", "Jane Doe", "Omar Haddad"])] == ["Omar Haddad", "Jane Doe"]
    with pytest.raises(LookupError, match="Jane Doe or Jane Roe"):
        resolve_picks(ms, ["Jane"])
    with pytest.raises(LookupError, match="isn't on the guest list"):
        resolve_picks(ms, ["Zed"])


def test_picks_write_notes_event_and_undo(vault):
    guests = [Guest("Ann Lee", "Acme"), Guest("Dee Moss", facts={"Title": "Founder", "Company": "Moss Labs"}),
              Guest("Li Wei")]
    cap, _ = plan_guests(vault, guests, ["Ann", "Dee Moss"], event="Founders Night", today=TODAY)
    apply(cap, "guests")

    new = read(vault, "Atlas/People/Dee Moss.md")         # created next to the other people
    assert new.startswith("---\ntags: [person]\n---\n# Dee Moss\n\n## Overview\n\n## Key Facts\n"
                          "- **Title:** Founder\n- **Company:** Moss Labs\n")
    assert "## Notes\n- [[2026-10-13]] on the guest list for [[Founders Night]] (Founder, Moss Labs)\n" in new
    assert "- [[2026-10-02]]: Dee Moss is raising a seed round" in new      # vault evidence, linked back

    known = read(vault, "Atlas/People/Ann Lee.md")
    assert "- likes tea\n- [[2026-10-13]] on the guest list for [[Founders Night]] (Acme)\n" in known
    assert read(vault, "Events/Founders Night.md") == "# Founders Night\n\n## People to meet\n- [[Ann Lee]]\n- [[Dee Moss]]\n"
    assert not (vault.root / "Atlas/People/Li Wei.md").exists()            # not picked

    again, _ = plan_guests(vault, guests, ["Ann", "Dee Moss"], event="Founders Night", today=TODAY)
    assert again.edits == []                                                # nothing doubled

    journal.undo(vault.root)
    assert not (vault.root / "Atlas/People/Dee Moss.md").exists()
    assert read(vault, "Atlas/People/Ann Lee.md") == PEOPLE["Atlas/People/Ann Lee.md"]
    assert read(vault, "Events/Founders Night.md") == "# Founders Night\n"


def test_event_without_a_note_and_no_event(vault):
    cap, _ = plan_guests(vault, [Guest("Li Wei")], ["Li Wei"], event="Gala 2026", today=TODAY)
    assert cap.lines == {"Atlas/People/Li Wei.md": ["- [[2026-10-13]] on the guest list for [[Gala 2026]]"]}
    cap, _ = plan_guests(vault, [Guest("Li Wei")], ["Li Wei"], label="ie-mixer", today=TODAY)
    assert cap.lines["Atlas/People/Li Wei.md"] == ["- [[2026-10-13]] on the guest list for ie-mixer"]


def test_near_and_ambiguous_picks_are_refused(vault):
    with pytest.raises(LookupError, match="close to Jonas Weber"):
        plan_guests(vault, [Guest("Jonas K. Weber")], ["Jonas K. Weber"], today=TODAY)
    with pytest.raises(LookupError, match="alias"):
        plan_guests(vault, [Guest("Sam O")], ["Sam O"], today=TODAY)


def test_no_picks_writes_nothing(vault):
    cap, ms = plan_guests(vault, [Guest("Ann Lee"), Guest("Li Wei")], [], today=TODAY)
    assert cap.edits == [] and [m.status for m in ms] == ["known", "new"]


def test_a_list_kept_in_the_vault_is_not_a_mention(vault):
    f = vault.root / "Events/guests.md"
    f.write_text("- Ann Lee\n- Li Wei\n")
    cap, _ = plan_guests(vault, read_guest_list(f), ["Li Wei"], source=f, today=TODAY)
    assert "backlinker:dossier" not in next(e.after for e in cap.edits if e.path.name == "Li Wei.md")
