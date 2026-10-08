// E5: the brand-token check for a section the agent writes. Structure is free; style is the brand's.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { lint } from "./check-section";

const skill = fs.readFileSync(path.join(__dirname, "..", "agent", "skills-e5", "writing-a-section", "SKILL.md"), "utf-8");
const EXAMPLE = skill.split("```tsx")[1].split("```")[0];

const withClass = (classes: string) => EXAMPLE.replace("mt-6 font-body text-body text-ink-secondary", classes);

test("the skill's own example passes", () => {
  assert.deepEqual(lint(EXAMPLE), []);
});

test("layout measures are fine; brand tokens are fine", () => {
  assert.deepEqual(lint(withClass("mt-6 grid gap-8 md:grid-cols-3 max-w-[30ch] aspect-[4/3] rounded-card border-line-subtle bg-surface-muted font-title text-title")), []);
});

test("colour values, palette colours, default type and custom brackets are refused", () => {
  const cases: [string, RegExp][] = [
    ["mt-6 text-emerald-600", /palette colour/],
    ["mt-6 bg-white", /fixed colour/],
    ["mt-6 text-lg", /Tailwind type size/],
    ["mt-6 font-bold", /Tailwind font or weight/],
    ["mt-6 bg-[#7C4CFF]", /custom colour, type or corner/],
    ["mt-6 text-[18px]", /custom colour, type or corner/],
  ];
  for (const [classes, why] of cases) {
    const errors = lint(withClass(classes));
    assert.ok(errors.some((e) => why.test(e)), `${classes}: ${errors.join("; ")}`);
  }
});

test("inline style, raw colour values and other imports are refused", () => {
  assert.ok(lint(EXAMPLE.replace("<p className", "<p style={{ color: 'red' }} className")).some((e) => e.includes("inline style")));
  assert.ok(lint(EXAMPLE.replace("max-w-[30ch]", "max-w-[30ch]\" data-c=\"#ff0000")).some((e) => e.includes("colour value #ff0000")));
  assert.ok(lint(`import x from "lodash";\n${EXAMPLE}`).some((e) => e.includes('import "lodash"')));
});
