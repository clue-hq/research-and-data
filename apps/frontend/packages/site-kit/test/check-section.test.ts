// E5: the brand-token check for a section the agent writes. Structure is free; style is the brand's.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { LINK_REFUSAL, lint, typeCheck } from "../src/check-section";

// The example from the spike's writing-a-section skill (trials/puck-spike/agent/skills-e5/), verbatim.
const EXAMPLE = fs.readFileSync(new URL("./fixtures/section-example.tsx", import.meta.url), "utf-8");

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

test("the type check runs on a file written inside the package", () => {
  // A hidden directory, so neither this package's nor the frontend's tsconfig picks the files up.
  const dir = fileURLToPath(new URL("../.section-check/type-check-test", import.meta.url));
  fs.mkdirSync(dir, { recursive: true });
  try {
    const good = path.join(dir, "Good.tsx");
    fs.writeFileSync(good, EXAMPLE);
    assert.deepEqual(typeCheck(good), []);
    const bad = path.join(dir, "Bad.tsx");
    fs.writeFileSync(bad, EXAMPLE.replace("</kit.Shell>", "<kit.Button href=\"/x\">Go</kit.Button></kit.Shell>"));
    const errors = typeCheck(bad);
    assert.ok(errors.some((e) => e.includes("TS2322")), errors.join("; ") || "no type errors");
  } finally {
    fs.rmSync(path.dirname(dir), { recursive: true, force: true });
  }
});

const HOSTILE = (name: string) =>
  fs.readFileSync(new URL(`./fixtures/hostile/${name}.tsx`, import.meta.url), "utf-8");

test("the D2 banned names refuse the four hostile sections that name them", () => {
  const cases: [string, RegExp][] = [
    ["NetworkCall", /^"fetch" is a network call/],
    ["CookieRead", /^"document" reaches the page outside the section/],
    ["ParentFrame", /^"window" reaches the page outside the section/],
    ["InjectedScript", /^"dangerouslySetInnerHTML" writes raw HTML/],
  ];
  for (const [name, why] of cases) {
    const errors = lint(HOSTILE(name));
    assert.ok(errors.some((e) => why.test(e)), `${name}: ${errors.join("; ")}`);
  }
});

test("resource abuse names nothing banned: the loop and the huge page pass (the render page bounds them)", () => {
  assert.deepEqual(lint(HOSTILE("InfiniteLoop")), []);
  assert.deepEqual(lint(HOSTILE("HugeOutput")), []);
});

test("a banned word in a section's text is not a banned name", () => {
  const prose = EXAMPLE.replace("{props.attribution}", "{props.attribution} window document fetch cookie");
  assert.deepEqual(lint(prose), []);
});

test("event handlers and dynamic imports are refused by name", () => {
  const handler = lint(EXAMPLE.replace("<p className", "<p onClick={() => 0} className"));
  assert.ok(handler.includes('"onClick" is an event handler; a section is static'), handler.join("; "));
  const dynamic = lint(`${EXAMPLE}\nexport const later = () => import("./x");\n`);
  assert.ok(dynamic.some((e) => e.startsWith('"import(" loads code the check never saw')), dynamic.join("; "));
});

test("the CLI checks a section without importing it", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const dir = path.join(root, ".section-check", "cli-test");
  fs.mkdirSync(dir, { recursive: true });
  try {
    const file = path.join(dir, "Loud.tsx");
    // A module that throws the moment anything imports it: the CLI must still answer ok.
    fs.writeFileSync(file, `${EXAMPLE}\nthrow new Error("the check imported the section");\n`);
    const out = execFileSync(process.execPath, ["--import", "tsx", "src/check-section.ts", file], { cwd: root });
    assert.deepEqual(JSON.parse(out.toString()), { ok: true, errors: [] });
  } finally {
    fs.rmSync(path.join(root, ".section-check"), { recursive: true, force: true });
  }
});

test("a raw <a> is refused; links go through kit.Link or kit.Button", () => {
  const errors = lint(EXAMPLE.replace("</kit.Shell>", '<a href="/analysis">More</a></kit.Shell>'));
  assert.ok(errors.includes(LINK_REFUSAL), errors.join("; "));
});

test("a colour class the theme does not define is refused by name", () => {
  for (const cls of ["border-line-inverse", "bg-surface-brandSubtle", "text-ink-tertiary"]) {
    const errors = lint(withClass(`mt-6 ${cls}`));
    assert.ok(errors.some((e) => e.startsWith(`class "${cls}" is not one of the brand's classes`)), `${cls}: ${errors.join("; ")}`);
  }
});

test("variants, opacity and every defined colour class pass", () => {
  assert.deepEqual(lint(withClass("mt-6 md:bg-surface-muted hover:border-line-subtle/50 text-on-surface-brand ring-focus bg-surface-canvas")), []);
});

test("the kit's extra surfaces pass only when the brand has them", () => {
  const band = withClass("mt-6 bg-surface-band-statement text-on-surface-band-statement");
  assert.ok(lint(band).some((e) => e.startsWith('class "bg-surface-band-statement" is not one of the brand\'s classes')));
  assert.deepEqual(lint(band, { extraSurfaces: ["surface.band.statement"] }), []);
});
