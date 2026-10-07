// Port of insert_lines from backlinker/notes.py.
import { splitLines } from "./linker";

const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const LIST_ITEM = /^\s*(?:[-*+]|\d+[.)])\s/;

function parseHeading(line: string): [number, string] | null {
  const m = HEADING.exec(line.replace(/[\r\n]+$/, ""));
  return m ? [m[1].length, m[2].toLowerCase()] : null;
}

/** Add lines at the end of the section under `heading` (created if missing), or at the end of the note. */
export function insertLines(text: string, add: string[], heading = "", nl = "\n"): string {
  const lines = splitLines(text);
  const want: [number | null, string] = heading.trimStart().startsWith("#")
    ? (parseHeading(heading) ?? [null, heading.trim().toLowerCase()])
    : [null, heading.trim().toLowerCase()];

  const heads: [number, number, string][] = [];
  let fence: string | null = null;
  let inFront = lines.length > 0 && lines[0].trim() === "---";
  lines.forEach((line, i) => {
    const s = line.trim();
    if (inFront) inFront = !(i > 0 && (s === "---" || s === "..."));
    else if (fence) fence = s.startsWith(fence) ? null : fence;
    else if (s.startsWith("```") || s.startsWith("~~~")) fence = s.slice(0, 3);
    else { const h = parseHeading(line); if (h) heads.push([i, h[0], h[1]]); }
  });

  let start = -1, end = lines.length;
  if (heading) {
    const found = heads.find(([, lvl, title]) => title === want[1] && (want[0] === null || want[0] === lvl));
    if (!found) {
      const title = heading.trimStart().startsWith("#") ? heading.trim() : `## ${heading.trim()}`;
      const body = text.replace(/[\r\n]+$/, "");
      return (body ? body + nl + nl : "") + title + nl + add.map((l) => l + nl).join("");
    }
    start = found[0];
    end = heads.find(([i, l]) => i > start && l <= found[1])?.[0] ?? lines.length;
  }

  let last = start;
  for (let i = start + 1; i < end; i++) if (lines[i].trim()) last = i;
  if (last >= 0 && !/[\r\n]$/.test(lines[last])) lines[last] += nl;
  const prev = last >= 0 ? lines[last].trim() : "";
  const gap = prev && !LIST_ITEM.test(lines[last]) && !parseHeading(lines[last]) ? [nl] : [];
  lines.splice(last + 1, 0, ...gap, ...add.map((l) => l + nl));
  return lines.join("");
}
