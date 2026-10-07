import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { findDue, parseWhen } from "../src/dates";
import { Linker, notesFrom, protectedRe } from "../src/linker";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../../spec/${name}`, import.meta.url), "utf-8"));

describe("linker spec (shared with the Python CLI)", () => {
  const spec = read("linker-cases.json");
  const linker = new Linker(notesFrom(spec.notes, ["People"]));
  it.each(spec.cases.map((c: any) => [c.text, c]))("%s", (_t, c: any) => {
    const r = linker.link(c.text, [], c.table ?? false);
    expect(r.text, c.why).toBe(c.expect);
    expect(r.ambiguous.map((a) => a.text)).toEqual(c.ambiguous);
  });
  it.each(spec.documents.map((d: any) => [d.why, d]))("document: %s", (_w, d: any) => {
    expect(linker.linkDocument(d.text, d.self).text).toBe(d.expect);
  });
});

describe("date spec (shared with the Python CLI)", () => {
  const spec = read("date-cases.json");
  it.each(spec.due.map((c: any) => [c.text, c]))("due: %s", (_t, c: any) => {
    const spans = [...c.text.matchAll(protectedRe())].map((m: RegExpMatchArray) => [m.index!, m.index! + m[0].length]);
    expect(findDue(c.text, spec.today, spans as [number, number][])).toEqual([c.date, c.rest]);
  });
  it.each(spec.when.map((c: any) => [c.text, c]))("when: %s", (_t, c: any) => {
    if (c.date === null) expect(() => parseWhen(c.text, spec.today)).toThrow();
    else expect(parseWhen(c.text, spec.today)).toBe(c.date);
  });
});
