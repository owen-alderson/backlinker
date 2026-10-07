"""Turn plain text into [[wikilinks]] for notes that already exist.

Precision over recall: a wrong link is worse than a missing one, so
- only whole words match, and the longest name wins ("Maya Chen" before "Maya");
- names of 3 letters or fewer must match case exactly ("AI" never matches "ai");
- a person's first name links only when it is capitalised and belongs to one person;
- a name shared by two notes is reported as ambiguous and left alone;
- existing links, code, URLs, tags and emails are never touched;
- each note is linked once per text (the first mention).

spec/linker-cases.json pins this behaviour; plugin/src/linker.ts must pass the same cases.
"""

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

TOKEN = re.compile(r"\w+(?:['.&-]\w+)*(?:(?<=\.\w)\.)?")  # "J.P." keeps its last dot
PROTECTED = re.compile(
    r"!?\[\[[^\]\n]*\]\]"           # wikilinks and embeds
    r"|`[^`\n]*`"                    # inline code
    r"|!?\[[^\]\n]*\]\([^)\n]*\)"    # markdown links and images
    r"|<[^>\n]+>"                    # html and <autolinks>
    r"|[A-Za-z][\w+.-]*://\S+"       # urls
    r"|[\w.+-]+@[\w-]+\.[\w.-]+"     # emails
    r"|(?<![\w#])#[^\s#]+"           # #tags
    r"|\$[^$\n]+\$"                  # inline maths
)
WIKILINK = re.compile(r"!?\[\[([^\]|#^\n]*)[^\]\n]*\]\]")
# First words that are not first names ("The Native", "New Balance").
NOT_FIRST_NAMES = {"the", "a", "an", "new", "old", "my", "our", "your", "mr", "mrs", "ms", "dr",
                   "prof", "sir", "st", "saint", "san", "los", "las", "el", "la", "le", "de", "van",
                   "von", "big", "little", "north", "south", "east", "west", "great", "united"}


def normalise(s: str) -> str:
    """Same length as s, so match positions still line up with the original text."""
    return s.replace("’", "'").replace("‘", "'")


def key(name: str) -> str:
    return " ".join(t.casefold() for t in TOKEN.findall(normalise(name)))


def _letters(s: str) -> int:
    return sum(c.isalpha() for c in s)


def _base(target: str) -> str:
    return PurePosixPath(target).name.casefold()


@dataclass(frozen=True)
class Note:
    target: str              # what goes inside [[ ]]
    names: tuple[str, ...]   # file name first, then aliases
    person: bool = False


@dataclass(frozen=True)
class Link:
    target: str
    text: str
    start: int
    end: int

    def render(self, in_table: bool = False) -> str:
        if self.text == self.target:
            return f"[[{self.target}]]"
        sep = "\\|" if in_table else "|"  # a bare | would split a table cell
        return f"[[{self.target}{sep}{self.text}]]"


@dataclass
class Result:
    text: str
    links: list[Link] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)

    @property
    def targets(self) -> list[str]:
        return [l.target for l in self.links]


@dataclass(frozen=True)
class _Entry:
    target: str
    form: str    # the name as written in the vault
    kind: str    # "name", "short" (case-sensitive) or "first" (derived first name)


class Linker:
    def __init__(self, notes: list[Note], ignore: list[str] = ()):
        ignored = {key(i) for i in ignore}
        self._entries: dict[str, list[_Entry]] = {}
        self._longest = 1

        def add(k: str, entry: _Entry):
            self._entries.setdefault(k, []).append(entry)
            self._longest = max(self._longest, k.count(" ") + 1)

        for note in notes:
            for name in note.names:
                k = key(name)
                if not k or k in ignored or _letters(k) < 2:
                    continue  # empty, ignored, a single letter, or no letters at all (dates)
                add(k, _Entry(note.target, normalise(name), "short" if _letters(k) <= 3 else "name"))
            first = self._first_name(note)
            if first and key(first) not in ignored:
                add(key(first), _Entry(note.target, first, "first"))

    @staticmethod
    def _first_name(note: Note) -> str | None:
        if not note.person:
            return None
        tokens = TOKEN.findall(normalise(note.names[0]))
        if not 2 <= len(tokens) <= 4 or any(not re.fullmatch(r"[^\W\d_]+(?:['-][^\W\d_]+)*", t) for t in tokens):
            return None
        first = tokens[0]
        if len(first) < 3 or not first[0].isupper() or first.casefold() in NOT_FIRST_NAMES:
            return None
        return first

    def _resolve(self, k: str, span: str) -> set[str]:
        entries = self._entries.get(k, [])
        accepted = [e for e in entries if e.kind == "name"
                    or (e.kind == "short" and span == e.form)
                    or (e.kind == "first" and span[:1].isupper())]
        explicit = {e.target for e in accepted if e.kind != "first"}
        return explicit or {e.target for e in accepted}

    def link(self, text: str, skip: set[str] = frozenset(), in_table: bool = False) -> Result:
        """Link mentions in one piece of text. `skip`: lowercase note names already linked."""
        res, linked = Result(text), {_base(t) for t in skip}
        linked |= {_base(m.group(1)) for m in WIKILINK.finditer(text)}
        norm = normalise(text)
        reported = set()

        for gap_start, gap_end in self._unprotected(norm):
            toks = [m for m in TOKEN.finditer(norm, gap_start, gap_end)]
            i = 0
            while i < len(toks):
                for n in range(min(self._longest, len(toks) - i), 0, -1):
                    window = toks[i:i + n]
                    if any(not re.fullmatch(r"[ \t]+", norm[a.end():b.start()]) for a, b in zip(window, window[1:])):
                        continue
                    start, end = window[0].start(), window[-1].end()
                    k = " ".join(t.group().casefold() for t in window)
                    targets = self._resolve(k, norm[start:end])
                    if not targets and k.endswith("'s"):  # possessive: "Maya's deck"
                        end -= 2
                        targets = self._resolve(k[:-2], norm[start:end])
                    if not targets:
                        continue
                    if len(targets) > 1:
                        if k not in reported:
                            res.ambiguous.append({"text": text[start:end], "candidates": sorted(targets)})
                            reported.add(k)
                    else:
                        (target,) = targets
                        if _base(target) not in linked:
                            res.links.append(Link(target, text[start:end], start, end))
                            linked.add(_base(target))
                    i += n
                    break
                else:
                    i += 1

        out, pos = [], 0
        for l in res.links:
            out += [text[pos:l.start], l.render(in_table)]
            pos = l.end
        res.text = "".join(out) + text[pos:]
        return res

    @staticmethod
    def _unprotected(text: str):
        pos = 0
        for m in PROTECTED.finditer(text):
            yield pos, m.start()
            pos = m.end()
        yield pos, len(text)

    def link_document(self, text: str, self_target: str | None = None) -> Result:
        """Link unlinked mentions across a whole note, skipping frontmatter, code blocks and
        headings, and any note the document already links to."""
        skip = {m.group(1) for m in WIKILINK.finditer(text)}
        if self_target:
            skip.add(self_target)
        lines = text.splitlines(keepends=True)
        out, res = [], Result(text)
        in_front = bool(lines) and lines[0].strip() == "---"
        fence = None
        offset = 0
        for n, line in enumerate(lines):
            stripped = line.strip()
            if in_front:
                out.append(line)
                if n > 0 and stripped in ("---", "..."):
                    in_front = False
            elif fence:
                out.append(line)
                if stripped.startswith(fence):
                    fence = None
            elif stripped.startswith(("```", "~~~")):
                fence = stripped[:3]
                out.append(line)
            elif stripped.startswith("#") and re.match(r"#{1,6}\s", stripped) or stripped.startswith("%%"):
                out.append(line)
            else:
                r = self.link(line, skip=skip, in_table=stripped.startswith("|"))
                skip |= set(r.targets)
                res.links += [Link(l.target, l.text, l.start + offset, l.end + offset) for l in r.links]
                seen = {a["text"].casefold() for a in res.ambiguous}
                res.ambiguous += [a for a in r.ambiguous if a["text"].casefold() not in seen]
                out.append(r.text)
            offset += len(line)
        res.text = "".join(out)
        return res
