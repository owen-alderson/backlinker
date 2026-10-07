import pytest

from backlinker.notes import NoteNotFound, find_note, insert_lines

ENTRIES = [("People/Maya Chen.md", ["MC"], ["person"]), ("People/Sam Okafor.md", [], ["person"]),
           ("People/Sam Patel.md", [], ["person"]), ("A/Harbor.md", [], []), ("B/Harbor.md", [], []),
           ("Companies/Lumen Labs.md", ["Lumen"], [])]


@pytest.mark.parametrize("query,rel", [
    ("Maya Chen", "People/Maya Chen.md"), ("maya chen", "People/Maya Chen.md"), ("MC", "People/Maya Chen.md"),
    ("Maya", "People/Maya Chen.md"), ("Lumen", "Companies/Lumen Labs.md"), ("A/Harbor", "A/Harbor.md"),
    ("People/Sam Patel.md", "People/Sam Patel.md"),
])
def test_find_note(query, rel):
    assert find_note(ENTRIES, query) == rel


def test_find_note_ambiguous_lists_candidates():
    with pytest.raises(NoteNotFound, match="2 notes: A/Harbor, B/Harbor"):
        find_note(ENTRIES, "Harbor")
    with pytest.raises(NoteNotFound, match="2 notes: People/Sam Okafor, People/Sam Patel"):
        find_note(ENTRIES, "Sam")  # two Sams: say which, never pick one


def test_find_note_suggests_close_names():
    with pytest.raises(NoteNotFound, match="did you mean 'Maya Chen'"):
        find_note(ENTRIES, "Maya Chan")


def test_append_to_end_of_list():
    assert insert_lines("# Day\n\n- a\n", ["- b"]) == "# Day\n\n- a\n- b\n"


def test_append_after_paragraph_adds_blank_line():
    assert insert_lines("Some text", ["- b"]) == "Some text\n\n- b\n"


def test_append_to_empty_note():
    assert insert_lines("", ["- a", "- b"]) == "- a\n- b\n"


def test_trailing_blank_lines_stay_after_new_lines():
    assert insert_lines("- a\n\n\n", ["- b"]) == "- a\n- b\n\n\n"


def test_insert_at_end_of_heading_section_not_end_of_note():
    text = "# Day\n\n## Log\n- 09:00 a\n\n## Tasks\n- [ ] t\n"
    assert insert_lines(text, ["- 10:00 b"], "## Log") == "# Day\n\n## Log\n- 09:00 a\n- 10:00 b\n\n## Tasks\n- [ ] t\n"


def test_heading_without_hashes_matches_any_level_case_insensitively():
    text = "### log\n- a\n# Next\n"
    assert insert_lines(text, ["- b"], "Log") == "### log\n- a\n- b\n# Next\n"


def test_heading_level_must_match_when_given():
    text = "### Log\n- a\n"
    assert insert_lines(text, ["- b"], "## Log") == "### Log\n- a\n\n## Log\n- b\n"


def test_subheadings_belong_to_the_section():
    text = "## Log\n- a\n### detail\n- d\n## Other\n"
    assert insert_lines(text, ["- b"], "## Log") == "## Log\n- a\n### detail\n- d\n- b\n## Other\n"


def test_empty_section_gets_line_right_under_heading():
    assert insert_lines("## Log\n\n## Other\n", ["- b"], "## Log") == "## Log\n- b\n\n## Other\n"


def test_missing_heading_is_created_at_the_end():
    assert insert_lines("# Day\n- x\n", ["- b"], "Log") == "# Day\n- x\n\n## Log\n- b\n"
    assert insert_lines("", ["- b"], "## Log") == "## Log\n- b\n"


def test_headings_inside_code_and_frontmatter_are_ignored():
    text = "---\n# not: heading\n---\n```\n## Log\n```\n## Log\n- a\n"
    assert insert_lines(text, ["- b"], "## Log").endswith("```\n## Log\n- a\n- b\n")


def test_no_final_newline_and_crlf():
    assert insert_lines("- a", ["- b"]) == "- a\n- b\n"
    assert insert_lines("## Log\r\n- a\r\n", ["- b"], "## Log", "\r\n") == "## Log\r\n- a\r\n- b\r\n"


def test_frontmatter_only_note():
    assert insert_lines("---\ndate: x\n---\n", ["- a"]) == "---\ndate: x\n---\n\n- a\n"


def test_heading_without_space_after_hashes_is_matched_by_title():
    assert insert_lines("# Day\n", ["- b"], "#Log") == "# Day\n\n#Log\n- b\n"
