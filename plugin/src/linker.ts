// Port of backlinker/linker.py. spec/linker-cases.json pins the behaviour of both.
// Python's \w is Unicode-aware; in JavaScript that is [\p{L}\p{N}_] with the u flag.

const W = String.raw`[\p{L}\p{N}_]`;
const TOKEN_SRC = String.raw`${W}+(?:['.&-]${W}+)*(?:(?<=\.${W})\.)?`;
const PROTECTED_SRC = [
  String.raw`!?\[\[[^\]\n]*\]\]`,
  String.raw`\x60[^\x60\n]*\x60`,
  String.raw`!?\[[^\]\n]*\]\([^)\n]*\)`,
  String.raw`<[^>\n]+>`,
  String.raw`[A-Za-z][\p{L}\p{N}_+.-]*:\/\/\S+`,
  String.raw`[\p{L}\p{N}_.+-]+@[\p{L}\p{N}_-]+\.[\p{L}\p{N}_.-]+`,
  String.raw`(?<![\p{L}\p{N}_#])#[^\s#]+`,
  String.raw`\$[^$\n]+\$`,
].join("|");
const WIKILINK_SRC = String.raw`!?\[\[([^\]|#^\n]*)[^\]\n]*\]\]`;

export const protectedRe = () => new RegExp(PROTECTED_SRC, "gu");
const tokenRe = () => new RegExp(TOKEN_SRC, "gu");
const wikilinkRe = () => new RegExp(WIKILINK_SRC, "gu");

const NOT_FIRST_NAMES = new Set(["the", "a", "an", "new", "old", "my", "our", "your", "mr", "mrs", "ms", "dr",
  "prof", "sir", "st", "saint", "san", "los", "las", "el", "la", "le", "de", "van", "von", "big", "little",
  "north", "south", "east", "west", "great", "united"]);

export interface Note { target: string; names: string[]; person: boolean }
export interface Link { target: string; text: string; start: number; end: number }
export interface Ambiguous { text: string; candidates: string[] }
export interface Result { text: string; links: Link[]; ambiguous: Ambiguous[] }
interface Entry { target: string; form: string; kind: "name" | "short" | "first" }

export const normalise = (s: string) => s.replace(/[’‘]/g, "'");
const lower = (s: string) => s.toLowerCase();
export const key = (name: string) => (normalise(name).match(tokenRe()) ?? []).map(lower).join(" ");
const letters = (s: string) => (s.match(/\p{L}/gu) ?? []).length;
const isUpper = (c: string) => c !== c.toLowerCase() && c === c.toUpperCase();
const base = (target: string) => lower(target.split("/").pop() ?? target);

export function render(l: Link, inTable = false): string {
  if (l.text === l.target) return `[[${l.target}]]`;
  return `[[${l.target}${inTable ? "\\|" : "|"}${l.text}]]`;
}

/** What to write inside [[ ]]: the bare name, or the path when two notes share a name. */
export function linkTargets(paths: string[]): Map<string, string> {
  const stem = (p: string) => (p.split("/").pop() ?? p).replace(/\.md$/, "");
  const counts = new Map<string, number>();
  for (const p of paths) counts.set(lower(stem(p)), (counts.get(lower(stem(p))) ?? 0) + 1);
  return new Map(paths.map((p) => [p, counts.get(lower(stem(p))) === 1 ? stem(p) : p.replace(/\.md$/, "")]));
}

export function isPerson(path: string, tags: string[], peopleFolders: string[]): boolean {
  const folders = new Set(peopleFolders.map(lower));
  const parts = path.split("/").slice(0, -1);
  return parts.some((p) => folders.has(lower(p)))
    || tags.some((t) => lower(t.replace(/^#/, "")).split("/").some((s) => s === "person" || s === "people"));
}

export function notesFrom(entries: { path: string; aliases: string[]; tags: string[] }[], peopleFolders: string[]): Note[] {
  const targets = linkTargets(entries.map((e) => e.path));
  return entries.map((e) => ({
    target: targets.get(e.path)!,
    names: [(e.path.split("/").pop() ?? e.path).replace(/\.md$/, ""), ...e.aliases],
    person: isPerson(e.path, e.tags, peopleFolders),
  }));
}

function firstName(note: Note): string | null {
  if (!note.person) return null;
  const tokens = normalise(note.names[0]).match(tokenRe()) ?? [];
  if (tokens.length < 2 || tokens.length > 4) return null;
  if (tokens.some((t) => !/^\p{L}+(?:['-]\p{L}+)*$/u.test(t))) return null;
  const first = tokens[0]!;
  if (first.length < 3 || !isUpper(first[0]) || NOT_FIRST_NAMES.has(lower(first))) return null;
  return first;
}

export class Linker {
  private entries = new Map<string, Entry[]>();
  private longest = 1;

  constructor(notes: Note[], ignore: string[] = []) {
    const ignored = new Set(ignore.map(key));
    const add = (k: string, e: Entry) => {
      if (!this.entries.has(k)) this.entries.set(k, []);
      this.entries.get(k)!.push(e);
      this.longest = Math.max(this.longest, k.split(" ").length);
    };
    for (const note of notes) {
      for (const name of note.names) {
        const k = key(name);
        if (!k || ignored.has(k) || letters(k) < 2) continue;
        add(k, { target: note.target, form: normalise(name), kind: letters(k) <= 3 ? "short" : "name" });
      }
      const first = firstName(note);
      if (first && !ignored.has(key(first))) add(key(first), { target: note.target, form: first, kind: "first" });
    }
  }

  /** Same rule as the Python CLI: --to accepts a person's unique first name. */
  static firstName = firstName;

  private resolve(k: string, span: string): Set<string> {
    const accepted = (this.entries.get(k) ?? []).filter((e) => e.kind === "name"
      || (e.kind === "short" && span === e.form)
      || (e.kind === "first" && span.length > 0 && isUpper(span[0])));
    const explicit = new Set(accepted.filter((e) => e.kind !== "first").map((e) => e.target));
    return explicit.size ? explicit : new Set(accepted.map((e) => e.target));
  }

  private *unprotected(text: string): Generator<[number, number]> {
    let pos = 0;
    for (const m of text.matchAll(protectedRe())) {
      yield [pos, m.index!];
      pos = m.index! + m[0].length;
    }
    yield [pos, text.length];
  }

  link(text: string, skip: Iterable<string> = [], inTable = false): Result {
    const res: Result = { text, links: [], ambiguous: [] };
    const linked = new Set([...skip].map(base));
    for (const m of text.matchAll(wikilinkRe())) linked.add(base(m[1]));
    const norm = normalise(text);
    const reported = new Set<string>();

    for (const [gs, ge] of this.unprotected(norm)) {
      const toks: RegExpExecArray[] = [];
      const re = tokenRe();
      re.lastIndex = gs;  // like Python's finditer(text, pos, endpos)
      for (let m; (m = re.exec(norm.slice(0, ge))); ) toks.push(m);
      let i = 0;
      while (i < toks.length) {
        let matched = false;
        for (let n = Math.min(this.longest, toks.length - i); n > 0; n--) {
          const win = toks.slice(i, i + n);
          if (win.some((t, j) => j > 0 && !/^[ \t]+$/.test(norm.slice(win[j - 1].index! + win[j - 1][0].length, t.index!)))) continue;
          const start = win[0].index!;
          let end = win[n - 1].index! + win[n - 1][0].length;
          let k = win.map((t) => lower(t[0])).join(" ");
          let targets = this.resolve(k, norm.slice(start, end));
          if (!targets.size && k.endsWith("'s")) {
            end -= 2;
            k = k.slice(0, -2);
            targets = this.resolve(k, norm.slice(start, end));
          }
          if (!targets.size) continue;
          if (targets.size > 1) {
            if (!reported.has(k)) {
              res.ambiguous.push({ text: text.slice(start, end), candidates: [...targets].sort() });
              reported.add(k);
            }
          } else {
            const [target] = targets;
            if (!linked.has(base(target))) {
              res.links.push({ target, text: text.slice(start, end), start, end });
              linked.add(base(target));
            }
          }
          i += n;
          matched = true;
          break;
        }
        if (!matched) i += 1;
      }
    }

    let out = "", pos = 0;
    for (const l of res.links) {
      out += text.slice(pos, l.start) + render(l, inTable);
      pos = l.end;
    }
    res.text = out + text.slice(pos);
    return res;
  }

  /** Link unlinked mentions across a note: skips frontmatter, code blocks, headings, %% comments. */
  linkDocument(text: string, selfTarget: string | null = null): Result {
    const skip = new Set<string>([...text.matchAll(wikilinkRe())].map((m) => m[1]));
    if (selfTarget) skip.add(selfTarget);
    const lines = splitLines(text);
    const res: Result = { text, links: [], ambiguous: [] };
    const out: string[] = [];
    let inFront = lines.length > 0 && lines[0].trim() === "---";
    let fence: string | null = null;
    let offset = 0;
    lines.forEach((line, n) => {
      const s = line.trim();
      if (inFront) {
        out.push(line);
        if (n > 0 && (s === "---" || s === "...")) inFront = false;
      } else if (fence) {
        out.push(line);
        if (s.startsWith(fence)) fence = null;
      } else if (s.startsWith("```") || s.startsWith("~~~")) {
        fence = s.slice(0, 3);
        out.push(line);
      } else if (/^#{1,6}\s/.test(s) || s.startsWith("%%")) {
        out.push(line);
      } else {
        const r = this.link(line, skip, s.startsWith("|"));
        r.links.forEach((l) => skip.add(l.target));
        res.links.push(...r.links.map((l) => ({ ...l, start: l.start + offset, end: l.end + offset })));
        const seen = new Set(res.ambiguous.map((a) => lower(a.text)));
        res.ambiguous.push(...r.ambiguous.filter((a) => !seen.has(lower(a.text))));
        out.push(r.text);
      }
      offset += line.length;
    });
    res.text = out.join("");
    return res;
  }
}

/** Lines with their line endings, like Python's str.splitlines(keepends=True) for \n and \r\n. */
export function splitLines(text: string): string[] {
  return text.match(/[^\n]*\n|[^\n]+$/g) ?? [];
}
