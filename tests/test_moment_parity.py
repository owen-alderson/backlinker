"""format_moment against real moment.js output (spec/moment-cases.json, made by plugin/scripts/moment-cases.mjs)."""

import json
from datetime import datetime

from backlinker.dates import format_moment
from conftest import SPEC

CASES = json.loads((SPEC / "moment-cases.json").read_text(encoding="utf-8"))["cases"]


def test_matches_moment_exactly():
    wrong = [(c["at"], c["format"], c["expect"], format_moment(datetime.fromisoformat(c["at"]), c["format"]))
             for c in CASES
             if format_moment(datetime.fromisoformat(c["at"]), c["format"]) != c["expect"]]
    assert not wrong, wrong[:5]
    assert len(CASES) > 1000
