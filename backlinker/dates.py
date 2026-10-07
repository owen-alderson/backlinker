"""Dates: Obsidian's moment.js formats, and the few date phrases we trust.

Precision over coverage: a phrase is only read as a date when there is one sensible
reading. Numeric dates like 10/9 are never parsed (October 9th or 10 September?).
"""

import re
from datetime import date, datetime, timedelta

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ── moment.js formatting ──────────────────────────────────────────────────────

_MOMENT_TOKEN = re.compile(
    r"\[[^\]]*\]|YYYY|YY|Q|MMMM|MMM|MM|M|DDDD|DDD|Do|DD|D|dddd|ddd|dd|d|E|e"
    r"|GGGG|gggg|WW|W|ww|w|HH|H|hh|h|mm|m|ss|s|A|a|X"
)


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}" + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _week(d: date, dow: int, doy: int) -> tuple[int, int]:
    """moment's weekOfYear: dow = first day of week (0 = Sunday), doy = dow + 6 - janX."""

    def first_week_offset(year: int) -> int:
        fwd = 7 + dow - doy
        fwdlw = (7 + (date(year, 1, fwd).weekday() + 1) % 7 - dow) % 7
        return -fwdlw + fwd - 1

    def weeks_in_year(year: int) -> int:
        days = (date(year + 1, 1, 1) - date(year, 1, 1)).days
        return (days - first_week_offset(year) + first_week_offset(year + 1)) // 7

    week = (d.timetuple().tm_yday - first_week_offset(d.year) - 1) // 7 + 1
    if week < 1:
        return d.year - 1, week + weeks_in_year(d.year - 1)
    if week > weeks_in_year(d.year):
        return d.year + 1, week - weeks_in_year(d.year)
    return d.year, week


def format_moment(when: date | datetime, fmt: str) -> str:
    """Format like moment.js (English locale), which is what Obsidian uses for daily notes."""
    dt = when if isinstance(when, datetime) else datetime(when.year, when.month, when.day)

    def token(m: re.Match) -> str:
        t = m.group()
        if t.startswith("["):
            return t[1:-1]
        moment_day = (dt.weekday() + 1) % 7  # Sunday = 0
        hour12 = dt.hour % 12 or 12
        return {
            "YYYY": f"{dt.year:04d}", "YY": f"{dt.year % 100:02d}", "Q": str((dt.month - 1) // 3 + 1),
            "MMMM": MONTHS[dt.month - 1], "MMM": MONTHS[dt.month - 1][:3],
            "MM": f"{dt.month:02d}", "M": str(dt.month),
            "DDDD": f"{dt.timetuple().tm_yday:03d}", "DDD": str(dt.timetuple().tm_yday),
            "Do": _ordinal(dt.day), "DD": f"{dt.day:02d}", "D": str(dt.day),
            "dddd": DAYS[dt.weekday()], "ddd": DAYS[dt.weekday()][:3], "dd": DAYS[dt.weekday()][:2],
            "d": str(moment_day), "e": str(moment_day), "E": str(dt.isoweekday()),
            "GGGG": f"{_week(dt.date(), 1, 4)[0]:04d}", "WW": f"{_week(dt.date(), 1, 4)[1]:02d}",
            "W": str(_week(dt.date(), 1, 4)[1]),
            "gggg": f"{_week(dt.date(), 0, 6)[0]:04d}", "ww": f"{_week(dt.date(), 0, 6)[1]:02d}",
            "w": str(_week(dt.date(), 0, 6)[1]),
            "HH": f"{dt.hour:02d}", "H": str(dt.hour), "hh": f"{hour12:02d}", "h": str(hour12),
            "mm": f"{dt.minute:02d}", "m": str(dt.minute), "ss": f"{dt.second:02d}", "s": str(dt.second),
            "A": "AM" if dt.hour < 12 else "PM", "a": "am" if dt.hour < 12 else "pm",
            "X": str(int(dt.timestamp())),
        }[t]

    return _MOMENT_TOKEN.sub(token, fmt)


# ── Date phrases ──────────────────────────────────────────────────────────────

_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thurs": 3, "thur": 3, "thu": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
_MONTHS = {m.lower(): i + 1 for i, m in enumerate(MONTHS)}
_MONTHS.update({m[:3].lower(): i + 1 for i, m in enumerate(MONTHS)})
_MONTHS["sept"] = 9
_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

_WD = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))
_MO = "|".join(sorted(_MONTHS, key=len, reverse=True))
_NUM = r"\d{1,3}|" + "|".join(_NUMBERS)

_PHRASE = re.compile(
    rf"\b(?:"
    rf"(?P<iso>\d{{4}}-\d{{2}}-\d{{2}})"
    rf"|(?P<rel>today|tonight|tomorrow|tmrw|yesterday)"
    rf"|in (?P<in_n>{_NUM}) (?P<in_unit>days?|weeks?)"
    rf"|(?P<ago_n>{_NUM}) (?P<ago_unit>days?|weeks?) ago"
    rf"|(?P<nextweek>next week)"
    rf"|(?:(?P<which>next|this|last) )?(?P<wd>{_WD})"
    rf"|(?P<mo1>{_MO})\.? (?P<d1>\d{{1,2}})(?:st|nd|rd|th)?"
    rf"|(?P<d2>\d{{1,2}})(?:st|nd|rd|th)? (?:of )?(?P<mo2>{_MO})"
    rf")\b",
    re.IGNORECASE,
)
_CONNECTOR = re.compile(r"\b(?:on|by|due|before|until|for)\s+$", re.IGNORECASE)


def _count(word: str) -> int:
    return int(word) if word.isdigit() else _NUMBERS[word.lower()]


def _resolve(m: re.Match, today: date) -> date | None:
    g = m.groupdict()
    if g["iso"]:
        try:
            return date.fromisoformat(g["iso"])
        except ValueError:
            return None
    if g["rel"]:
        return today + timedelta(days={"yesterday": -1, "tomorrow": 1, "tmrw": 1}.get(g["rel"].lower(), 0))
    if g["in_n"]:
        n = _count(g["in_n"])
        return today + timedelta(days=n * (7 if g["in_unit"].lower().startswith("week") else 1))
    if g["ago_n"]:
        n = _count(g["ago_n"])
        return today - timedelta(days=n * (7 if g["ago_unit"].lower().startswith("week") else 1))
    if g["nextweek"]:
        return today + timedelta(days=7 - today.weekday())  # Monday of next week
    if g["wd"]:
        target = _WEEKDAYS[g["wd"].lower()]
        which = (g["which"] or "").lower()
        if which == "last":
            return today - timedelta(days=(today.weekday() - target - 1) % 7 + 1)
        ahead = (target - today.weekday() - 1) % 7 + 1  # the coming one, never today
        if which == "next":
            # "next friday" = the Friday of next calendar week (Mon-Sun weeks)
            monday_next = today + timedelta(days=7 - today.weekday())
            return monday_next + timedelta(days=target)
        return today + timedelta(days=ahead)
    month = _MONTHS[(g["mo1"] or g["mo2"]).lower()]
    day = int(g["d1"] or g["d2"])
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= today:
            return d
    return None


def _usable(m: re.Match, text: str) -> bool:
    """Short weekday names (sat, sun, wed...) are ordinary words too; only trust them
    after a connector ("on sat", "next wed"), at the very end of the line, or as a "Fri:" label."""
    wd = m.group("wd")
    if not wd or len(wd) > 4 or wd.lower() in ("tues", "thur"):
        return True
    if m.group("which"):
        return True
    if not text[: m.start()].strip() and text[m.end():].lstrip().startswith(":"):
        return True  # "Fri: send invoice"
    return bool(_CONNECTOR.search(text[: m.start()])) or not text[m.end():].strip(" .,;!?")


def find_due(text: str, today: date, protected: list[tuple[int, int]] = ()) -> tuple[date | None, str]:
    """Find the first trusted date phrase in a task. Returns (date, text without the phrase)."""
    for m in _PHRASE.finditer(text):
        if any(a <= m.start() < b for a, b in protected) or not _usable(m, text):
            continue
        if m.group("rel") and m.group("rel").lower() == "yesterday" or m.group("ago_n") \
                or (m.group("which") or "").lower() == "last":
            continue  # a due date is never in the past
        when = _resolve(m, today)
        if when is None:
            continue
        before = _CONNECTOR.sub("", text[: m.start()])
        rest = (before.rstrip() + " " + text[m.end():].lstrip()).strip()
        rest = re.sub(r"\s+([,.;!?])", r"\1", re.sub(r"\s{2,}", " ", rest)).strip(" ,;:")
        return when, rest
    return None, text


def parse_when(phrase: str, today: date) -> date:
    """Parse a whole phrase such as 'yesterday', 'fri', 'last tue', 'oct 9', '2026-10-09'."""
    phrase = phrase.strip()
    m = _PHRASE.fullmatch(phrase)
    when = _resolve(m, today) if m else None
    if when is None:
        raise ValueError(
            f"can't read {phrase!r} as a date; try 2026-10-09, today, yesterday, fri, last fri, oct 9"
        )
    return when
