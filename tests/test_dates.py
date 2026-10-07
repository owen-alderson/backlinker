from datetime import date, datetime

import pytest

from backlinker.dates import format_moment


@pytest.mark.parametrize("fmt,expect", [
    ("YYYY-MM-DD", "2026-10-07"), ("YYYY/MM/YYYY-MM-DD", "2026/10/2026-10-07"),
    ("dddd, MMMM Do YYYY", "Wednesday, October 7th 2026"), ("ddd D MMM YY", "Wed 7 Oct 26"),
    ("[Week] W, Q", "Week 41, 4"), ("DDDD", "280"), ("d E dd", "3 3 We"),
    ("HH:mm:ss A h a", "14:32:05 PM 2 pm"), ("[YYYY] YYYY", "YYYY 2026"), ("M/D", "10/7"),
])
def test_format_tokens(fmt, expect):
    assert format_moment(datetime(2026, 10, 7, 14, 32, 5), fmt) == expect


@pytest.mark.parametrize("n,suffix", [(1, "st"), (2, "nd"), (3, "rd"), (4, "th"), (11, "th"), (12, "th"),
                                      (13, "th"), (21, "st"), (22, "nd"), (23, "rd"), (31, "st")])
def test_ordinals(n, suffix):
    assert format_moment(date(2026, 1, n), "Do") == f"{n}{suffix}"


@pytest.mark.parametrize("day,iso,locale", [
    # (date, ISO GGGG-[W]WW, locale gggg-[w]ww)  US weeks start Sunday; week 1 holds Jan 1
    (date(2026, 1, 1), "2026-W01", "2026-w01"), (date(2025, 12, 28), "2025-W52", "2026-w01"),
    (date(2024, 12, 30), "2025-W01", "2025-w01"), (date(2021, 1, 3), "2020-W53", "2021-w02"),
    (date(2027, 1, 1), "2026-W53", "2027-w01"), (date(2026, 12, 31), "2026-W53", "2027-w01"),
])
def test_week_numbers(day, iso, locale):
    assert format_moment(day, "GGGG-[W]WW") == iso
    assert format_moment(day, "gggg-[w]ww") == locale
