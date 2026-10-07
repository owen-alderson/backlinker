// Port of find_due / parse_when from backlinker/dates.py. spec/date-cases.json pins both.
// Dates are plain "YYYY-MM-DD" strings; arithmetic is done in UTC so time zones can't shift a day.

const WEEKDAYS: Record<string, number> = {
  monday: 0, mon: 0, tuesday: 1, tues: 1, tue: 1, wednesday: 2, wed: 2, thursday: 3, thurs: 3, thur: 3,
  thu: 3, friday: 4, fri: 4, saturday: 5, sat: 5, sunday: 6, sun: 6,
};
const MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
  "october", "november", "december"];
const MONTHS: Record<string, number> = { sept: 9 };
MONTH_NAMES.forEach((m, i) => { MONTHS[m] = i + 1; MONTHS[m.slice(0, 3)] = i + 1; });
const NUMBERS: Record<string, number> = { a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6,
  seven: 7, eight: 8, nine: 9, ten: 10 };

const alt = (o: Record<string, number>) => Object.keys(o).sort((a, b) => b.length - a.length).join("|");
const WD = alt(WEEKDAYS), MO = alt(MONTHS), NUM = String.raw`\d{1,3}|` + Object.keys(NUMBERS).join("|");
const PHRASE_SRC = String.raw`\b(?:` +
  String.raw`(?<iso>\d{4}-\d{2}-\d{2})` +
  String.raw`|(?<rel>today|tonight|tomorrow|tmrw|yesterday)` +
  String.raw`|in (?<in_n>${NUM}) (?<in_unit>days?|weeks?)` +
  String.raw`|(?<ago_n>${NUM}) (?<ago_unit>days?|weeks?) ago` +
  String.raw`|(?<nextweek>next week)` +
  String.raw`|(?:(?<which>next|this|last) )?(?<wd>${WD})` +
  String.raw`|(?<mo1>${MO})\.? (?<d1>\d{1,2})(?:st|nd|rd|th)?` +
  String.raw`|(?<d2>\d{1,2})(?:st|nd|rd|th)? (?:of )?(?<mo2>${MO})` +
  String.raw`)\b`;
const CONNECTOR = /\b(?:on|by|due|before|until|for)\s+$/i;

const toUTC = (iso: string) => { const [y, m, d] = iso.split("-").map(Number); return Date.UTC(y, m - 1, d); };
const fromUTC = (t: number) => new Date(t).toISOString().slice(0, 10);
const addDays = (iso: string, n: number) => fromUTC(toUTC(iso) + n * 86400000);
const weekday = (iso: string) => (new Date(toUTC(iso)).getUTCDay() + 6) % 7; // Monday = 0
const mod = (a: number, n: number) => ((a % n) + n) % n;

function validDate(y: number, m: number, d: number): string | null {
  const t = new Date(Date.UTC(y, m - 1, d));
  if (t.getUTCFullYear() !== y || t.getUTCMonth() !== m - 1 || t.getUTCDate() !== d) return null;
  return fromUTC(t.getTime());
}
const count = (w: string) => (/^\d+$/.test(w) ? Number(w) : NUMBERS[w.toLowerCase()]);

function resolve(g: Record<string, string | undefined>, today: string): string | null {
  if (g.iso) { const [y, m, d] = g.iso.split("-").map(Number); return validDate(y, m, d); }
  if (g.rel) return addDays(today, ({ yesterday: -1, tomorrow: 1, tmrw: 1 } as Record<string, number>)[g.rel.toLowerCase()] ?? 0);
  if (g.in_n) return addDays(today, count(g.in_n) * (g.in_unit!.toLowerCase().startsWith("week") ? 7 : 1));
  if (g.ago_n) return addDays(today, -count(g.ago_n) * (g.ago_unit!.toLowerCase().startsWith("week") ? 7 : 1));
  if (g.nextweek) return addDays(today, 7 - weekday(today));
  if (g.wd) {
    const target = WEEKDAYS[g.wd.toLowerCase()], which = (g.which ?? "").toLowerCase(), wd = weekday(today);
    if (which === "last") return addDays(today, -(mod(wd - target - 1, 7) + 1));
    if (which === "next") return addDays(today, 7 - wd + target);
    return addDays(today, mod(target - wd - 1, 7) + 1);
  }
  const month = MONTHS[(g.mo1 ?? g.mo2)!.toLowerCase()], day = Number(g.d1 ?? g.d2);
  const year = Number(today.slice(0, 4));
  for (const y of [year, year + 1]) {
    const d = validDate(y, month, day);
    if (d === null) return null;
    if (d >= today) return d;
  }
  return null;
}

function usable(m: RegExpExecArray, text: string): boolean {
  const wd = m.groups!.wd;
  if (!wd || wd.length > 4 || ["tues", "thur"].includes(wd.toLowerCase())) return true;
  if (m.groups!.which) return true;
  const end = m.index + m[0].length;
  if (!text.slice(0, m.index).trim() && text.slice(end).trimStart().startsWith(":")) return true;
  return CONNECTOR.test(text.slice(0, m.index)) || !text.slice(end).replace(/^[ .,;!?]+|[ .,;!?]+$/g, "");
}

/** The first trusted date phrase in a task, and the task without it. */
export function findDue(text: string, today: string, protectedSpans: [number, number][] = []): [string | null, string] {
  const re = new RegExp(PHRASE_SRC, "gi");
  for (let m; (m = re.exec(text)); ) {
    const g = m.groups!;
    if (protectedSpans.some(([a, b]) => a <= m!.index && m!.index < b) || !usable(m, text)) continue;
    if ((g.rel ?? "").toLowerCase() === "yesterday" || g.ago_n || (g.which ?? "").toLowerCase() === "last") continue;
    const when = resolve(g, today);
    if (when === null) continue;
    const before = text.slice(0, m.index).replace(CONNECTOR, "");
    let rest = (before.trimEnd() + " " + text.slice(m.index + m[0].length).trimStart()).trim();
    rest = rest.replace(/\s{2,}/g, " ").replace(/\s+([,.;!?])/g, "$1").replace(/^[ ,;:]+|[ ,;:]+$/g, "");
    return [when, rest];
  }
  return [null, text];
}

/** A whole phrase: yesterday, fri, last fri, oct 9, 2026-10-09. Throws if it isn't one. */
export function parseWhen(phrase: string, today: string): string {
  const m = new RegExp(`^(?:${PHRASE_SRC})$`, "i").exec(phrase.trim());
  const when = m ? resolve(m.groups!, today) : null;
  if (when === null) throw new Error(`can't read "${phrase}" as a date`);
  return when;
}
