import { describe, expect, it } from "vitest";
import { insertLines } from "../src/insert";

// Mirrors tests/test_notes.py so both implementations place lines identically.
describe("insertLines", () => {
  it.each([
    ["# Day\n\n- a\n", ["- b"], "", "# Day\n\n- a\n- b\n"],
    ["Some text", ["- b"], "", "Some text\n\n- b\n"],
    ["", ["- a", "- b"], "", "- a\n- b\n"],
    ["- a\n\n\n", ["- b"], "", "- a\n- b\n\n\n"],
    ["# Day\n\n## Log\n- 09:00 a\n\n## Tasks\n- [ ] t\n", ["- 10:00 b"], "## Log", "# Day\n\n## Log\n- 09:00 a\n- 10:00 b\n\n## Tasks\n- [ ] t\n"],
    ["### log\n- a\n# Next\n", ["- b"], "Log", "### log\n- a\n- b\n# Next\n"],
    ["### Log\n- a\n", ["- b"], "## Log", "### Log\n- a\n\n## Log\n- b\n"],
    ["## Log\n- a\n### detail\n- d\n## Other\n", ["- b"], "## Log", "## Log\n- a\n### detail\n- d\n- b\n## Other\n"],
    ["## Log\n\n## Other\n", ["- b"], "## Log", "## Log\n- b\n\n## Other\n"],
    ["# Day\n- x\n", ["- b"], "Log", "# Day\n- x\n\n## Log\n- b\n"],
    ["", ["- b"], "## Log", "## Log\n- b\n"],
    ["---\ndate: x\n---\n", ["- a"], "", "---\ndate: x\n---\n\n- a\n"],
    ["- a", ["- b"], "", "- a\n- b\n"],
    ["# Day\n", ["- b"], "#Log", "# Day\n\n#Log\n- b\n"],
  ])("%j + %j under %j", (text, add, heading, expected) => {
    expect(insertLines(text as string, add as string[], heading as string)).toBe(expected);
  });

  it("keeps CRLF", () => {
    expect(insertLines("## Log\r\n- a\r\n", ["- b"], "## Log", "\r\n")).toBe("## Log\r\n- a\r\n- b\r\n");
  });

  it("ignores headings in code and frontmatter", () => {
    const text = "---\n# not: heading\n---\n```\n## Log\n```\n## Log\n- a\n";
    expect(insertLines(text, ["- b"], "## Log").endsWith("```\n## Log\n- a\n- b\n")).toBe(true);
  });
});
