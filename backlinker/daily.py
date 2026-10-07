"""Daily notes, found and created the way Obsidian's Daily notes plugin does it."""

import re
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath

from backlinker.dates import format_moment
from backlinker.vaults import Vault

_VAR = re.compile(r"{{\s*(date|time|title|yesterday|tomorrow)\s*(?:([+-]\d+)([dw]))?\s*(?::(.+?))?\s*}}", re.I)


def daily_rel(vault: Vault, day: date) -> str:
    dn = vault.daily_notes()
    name = format_moment(day, dn.format)
    return f"{dn.folder}/{name}.md" if dn.folder else f"{name}.md"


def daily_path(vault: Vault, day: date) -> Path:
    return vault.note_path(daily_rel(vault, day))


def daily_link(vault: Vault, day: date) -> str:
    """The [[link]] to a day's note (its file name; folders in the format are left out)."""
    return PurePosixPath(daily_rel(vault, day)).stem


def render_template(template: str, vault: Vault, day: date, now: datetime) -> str:
    """Fill {{date}}, {{time}}, {{title}}, {{yesterday}}, {{tomorrow}}, {{date:FORMAT}}, {{date+1d}}."""
    fmt = vault.daily_notes().format
    title = format_moment(day, fmt)
    moment = datetime.combine(day, now.time())

    def sub(m: re.Match) -> str:
        var, amount, unit, custom = m.group(1).lower(), m.group(2), m.group(3), m.group(4)
        if var == "title":
            return title
        when = moment
        if var in ("yesterday", "tomorrow"):
            when = moment + timedelta(days=-1 if var == "yesterday" else 1)
        if amount:
            when = when + timedelta(days=int(amount) * (7 if unit.lower() == "w" else 1))
        if var == "time" and not custom and not amount:
            return format_moment(now, "HH:mm")
        return format_moment(when, custom or fmt)

    return _VAR.sub(sub, template)


def new_daily_text(vault: Vault, day: date, now: datetime) -> str:
    """What a brand-new daily note starts with: the configured template, or nothing."""
    template = vault.daily_notes().template
    if not template:
        return ""
    try:
        text = vault.note_path(template).read_text(encoding="utf-8")
    except OSError:
        return ""  # Obsidian also creates an empty note when the template is missing
    return render_template(text, vault, day, now)
