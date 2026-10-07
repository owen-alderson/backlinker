import json
from datetime import date

import pytest

from backlinker.dates import find_due, parse_when
from backlinker.linker import PROTECTED
from conftest import SPEC

DATA = json.loads((SPEC / "date-cases.json").read_text(encoding="utf-8"))
TODAY = date.fromisoformat(DATA["today"])


@pytest.mark.parametrize("case", DATA["due"], ids=lambda c: c["text"])
def test_due(case):
    when, rest = find_due(case["text"], TODAY, [m.span() for m in PROTECTED.finditer(case["text"])])
    assert (when.isoformat() if when else None, rest) == (case["date"], case["rest"])


@pytest.mark.parametrize("case", DATA["when"], ids=lambda c: c["text"])
def test_when(case):
    if case["date"] is None:
        with pytest.raises(ValueError):
            parse_when(case["text"], TODAY)
    else:
        assert parse_when(case["text"], TODAY).isoformat() == case["date"]
