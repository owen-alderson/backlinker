"""The shared golden cases (spec/linker-cases.json). The plugin runs the same file."""

import json

import pytest

from backlinker.index import notes_from
from backlinker.linker import Linker
from conftest import SPEC

SPEC_DATA = json.loads((SPEC / "linker-cases.json").read_text(encoding="utf-8"))
LINKER = Linker(notes_from([(n["path"], n["aliases"], n["tags"]) for n in SPEC_DATA["notes"]], ["People"]))


@pytest.mark.parametrize("case", SPEC_DATA["cases"], ids=lambda c: c["text"][:40])
def test_case(case):
    r = LINKER.link(case["text"], in_table=case.get("table", False))
    assert r.text == case["expect"], case["why"]
    assert [a["text"] for a in r.ambiguous] == case["ambiguous"]


@pytest.mark.parametrize("doc", SPEC_DATA["documents"], ids=lambda d: d["why"][:40])
def test_document(doc):
    assert LINKER.link_document(doc["text"], self_target=doc["self"]).text == doc["expect"]


def test_spec_is_big_enough():
    assert len(SPEC_DATA["cases"]) >= 40
