import os

from backlinker.index import is_person, link_targets, read_frontmatter, scan, load_notes
from backlinker.vaults import cache_dir


def fm(text):
    return read_frontmatter(text)


def test_inline_list_aliases_and_tags():
    assert fm("---\naliases: [Maya, \"Chen, M\"]\ntags: [person, team/eng]\n---\n") == \
        {"aliases": ["Maya", "Chen, M"], "tags": ["person", "team/eng"]}


def test_block_list_and_singular_keys():
    text = "---\nalias:\n  - Maya\n  - 'M. Chen'\ntag: person\n---\nbody"
    assert fm(text) == {"aliases": ["Maya", "M. Chen"], "tags": ["person"]}


def test_scalar_alias_and_hash_tags():
    assert fm("---\naliases: Maya\ntags: \"#person #vip\"\n---\n") == {"aliases": ["Maya"], "tags": ["person", "vip"]}


def test_no_frontmatter_or_unclosed():
    assert fm("# Title\naliases: [x]") == {"aliases": [], "tags": []}
    assert fm("") == {"aliases": [], "tags": []}


def test_frontmatter_stops_at_closing_fence():
    assert fm("---\ntitle: x\n---\naliases: [late]\n")["aliases"] == []


def test_link_targets_use_paths_only_when_names_clash():
    t = link_targets(["A/Harbor.md", "B/Harbor.md", "People/Maya Chen.md"])
    assert t == {"A/Harbor.md": "A/Harbor", "B/Harbor.md": "B/Harbor", "People/Maya Chen.md": "Maya Chen"}


def test_link_targets_clash_is_case_insensitive():
    assert link_targets(["a/Note.md", "b/note.md"]) == {"a/Note.md": "a/Note", "b/note.md": "b/note"}


def test_is_person_by_folder_or_tag():
    assert is_person("Atlas/People/X Y.md", [], ["People"])
    assert is_person("Crm/X Y.md", ["people/clients"], ["People"])
    assert is_person("x.md", ["Person"], [])
    assert not is_person("Companies/X.md", ["company"], ["People"])


def test_scan_skips_hidden_templates_and_excluded(make_vault):
    v = make_vault({
        "a.md": "", ".obsidian/x.md": "", ".trash/gone.md": "", "Templates/Daily.md": "",
        "Archive/old.md": "", "Sub/b.md": "", "notes.txt": "", ".hidden.md": "",
        ".obsidian/templates.json": {"folder": "Templates"},
    }, exclude=["Archive/"])
    assert [rel for rel, _, _ in scan(v)] == ["Sub/b.md", "a.md"]


def test_scan_cache_rereads_only_changed_files(make_vault, monkeypatch):
    v = make_vault({"a.md": "---\naliases: [one]\n---\n", "b.md": ""})
    assert dict((r, a) for r, a, _ in scan(v))["a.md"] == ["one"]
    assert any(cache_dir().iterdir())

    reads = []
    import backlinker.index as index
    real = index._head
    monkeypatch.setattr(index, "_head", lambda p, *a: reads.append(p.name) or real(p, *a))
    scan(v)
    assert reads == []  # nothing changed
    (v.root / "a.md").write_text("---\naliases: [two, three]\n---\n")
    os.utime(v.root / "a.md", ns=(1, 1))
    assert dict((r, a) for r, a, _ in scan(v))["a.md"] == ["two", "three"]
    assert reads == ["a.md"]


def test_scan_survives_corrupt_cache(make_vault):
    v = make_vault({"a.md": ""})
    scan(v)
    for f in cache_dir().iterdir():
        f.write_text("{not json")
    assert [r for r, _, _ in scan(v)] == ["a.md"]


def test_load_notes_marks_people(demo):
    notes = {n.target: n for n in load_notes(demo)}
    assert notes["Maya Chen"].person and notes["Maya Chen"].names == ("Maya Chen", "Maya C")
    assert not notes["Northwind Capital"].person
    assert "Daily" not in notes  # the template folder is not indexed
