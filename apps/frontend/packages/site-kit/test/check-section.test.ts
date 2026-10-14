// E5: the brand-token check for a section the agent writes. Structure is free; style is the brand's.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { LINK_REFUSAL, lint, lintOptionsFor, typeCheck } from "../src/check-section";
import { kitBrand } from "./fixtures/kits";

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
  assert.ok(lint(EXAMPLE.replace("max-w-[30ch]", "max-w-[30ch]\" fill=\"#ff0000")).some((e) => e.includes("colour value #ff0000")));
  assert.ok(lint(`import x from "lodash";\n${EXAMPLE}`).some((e) => e.includes('import "lodash"')));
});

const INLINE_STYLE = "inline style; style only with the brand's classes";

test("a style attribute on a JSX element is refused, once", () => {
  assert.deepEqual(lint(EXAMPLE.replace("<p className", '<p style={{ color: "red" }} className')), [INLINE_STYLE]);
});

test("a style key in an object is refused: React.createElement's props", () => {
  assert.deepEqual(lint(`${EXAMPLE}\nexport const box = () => React.createElement("div", { style: { color: "red" } });\n`), [INLINE_STYLE]);
});

test("a shorthand style key is refused", () => {
  assert.deepEqual(lint(`${EXAMPLE}\nconst s = { style };\n`), [INLINE_STYLE]);
});

test("prose that says \"style:\" is not an inline style, in a string or a template", () => {
  assert.deepEqual(lint(EXAMPLE.replace("attribution: z.string(),", 'attribution: z.string().default("Leadership style: hands-on."),')), []);
  assert.deepEqual(lint(EXAMPLE.replace("{props.attribution}", "{`style: ${props.attribution}`}")), []);
});

test("a literal look written in braces is checked like a quoted one", () => {
  const options = { buttonLooks: ["solid.1"], cardLooks: ["solid.1"] };
  const withButton = (look: string) => EXAMPLE.replace("</kit.Shell>", `<kit.Button label="Go" href="/" surface="page" look=${look} /></kit.Shell>`);
  const unknown = 'look "solid.123456" on kit.Button is not one of this brand\'s button styles; the styles are solid.1 (brand/brand.md, Buttons)';
  assert.deepEqual(lint(withButton('{"solid.123456"}'), options), [unknown]);
  assert.deepEqual(lint(withButton("{`solid.123456`}"), options), [unknown]);
  const withCard = EXAMPLE.replace("</kit.Shell>", "<kit.Card look={'solid.7'}>x</kit.Card></kit.Shell>");
  assert.deepEqual(lint(withCard, options), ['look "solid.7" on kit.Card is not one of this brand\'s card styles; the styles are solid.1 (brand/brand.md, Cards)']);
});

test("a look the section computes is not checked; the validator checks props", () => {
  const computed = EXAMPLE.replace("</kit.Shell>", '<kit.Button label="Go" href="/" surface="page" look={props.look} /></kit.Shell>');
  assert.deepEqual(lint(computed, { buttonLooks: ["solid.1"] }), []);
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
    fs.rmSync(dir, { recursive: true, force: true });
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
    fs.rmSync(dir, { recursive: true, force: true });
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

test("a look named in the source must be one of the brand's", () => {
  const options = lintOptionsFor(kitBrand("garner"));
  const withButton = (look: string) => EXAMPLE.replace("</kit.Shell>", `<kit.Button label="Go" href="/" surface="page" look="${look}" /></kit.Shell>`);
  assert.deepEqual(lint(withButton("outline.1"), options), []);
  assert.ok(lint(withButton("solid.9"), options).includes('look "solid.9" on kit.Button is not one of this brand\'s button styles; the styles are outline.1, ghost.1, solid.1, solid.2, solid.3, solid.4 (brand/brand.md, Buttons)'));
  const withCard = EXAMPLE.replace("</kit.Shell>", '<kit.Card look="solid.7">x</kit.Card></kit.Shell>');
  assert.ok(lint(withCard, options).some((e) => e.startsWith('look "solid.7" on kit.Card is not one of this brand\'s card styles')));
});

test("motion of the section's own is refused; the brand's motion classes pass", () => {
  const options = lintOptionsFor(kitBrand("probe.minted"));
  for (const cls of ["transition", "duration-300", "ease-in-out", "animate-spin", "hover:scale-105", "group-hover:-translate-y-1", "focus:opacity-80"]) {
    assert.ok(lint(withClass(`mt-6 ${cls}`), options).some((e) => e.startsWith(`class "${cls}" is motion of your own`)), cls);
  }
  assert.deepEqual(lint(withClass("mt-6 brand-motion-pulse hover:bg-surface-muted -translate-x-1/2"), options), []);
  assert.ok(lint(withClass("mt-6 brand-motion-wobble"), options).some((e) => e.startsWith('class "brand-motion-wobble" is not one of this brand\'s motion classes')));
});

test("prose that mentions motion is never a class", () => {
  const options = lintOptionsFor(kitBrand("probe.minted"));
  const prose = EXAMPLE.replace(
    "attribution: z.string(),",
    'attribution: z.string().describe("A smooth transition built for ease-of-use"),\n  heading: z.string().default("Make the transition to value-based care"),',
  );
  assert.deepEqual(lint(prose, options), []);
});

test("prose with a number sign or a bracket is never a colour: text, attributes, schema defaults", () => {
  const cases: [string, string][] = [
    ["JSX text: an address", EXAMPLE.replace("{props.attribution}", "Suite #300, Main St")],
    ["JSX text: a hashtag", EXAMPLE.replace("{props.attribution}", "A #decade of results")],
    ["JSX text: a bracket", EXAMPLE.replace("{props.attribution}", "Visit our lab(s)")],
    ["a schema default", EXAMPLE.replace("attribution: z.string(),", 'attribution: z.string().default("Booth #A12"),')],
    ["alt", EXAMPLE.replace("</kit.Shell>", '<kit.Image src="/asset-store/x" alt="Booth #A12" /></kit.Shell>')],
    ["title", EXAMPLE.replace("<p className", '<p title="Call us: #300" className')],
    ["a link to an anchor", EXAMPLE.replace("</kit.Shell>", '<kit.Link href="#abc123">Jump</kit.Link></kit.Shell>')],
  ];
  for (const [where, source] of cases) assert.deepEqual(lint(source), [], where);
});

test("a colour value is refused wherever a colour can apply: className and the SVG colour attributes", () => {
  const svg = (element: string) => EXAMPLE.replace("</kit.Shell>", `<svg>${element}</svg></kit.Shell>`);
  assert.deepEqual(lint(svg('<path fill="#7C4CFF" />')), ["colour value #7C4CFF; use the brand's colour tokens"]);
  assert.deepEqual(lint(svg('<stop stopColor="rgb(1,2,3)" />')), ["colour function rgb(…); use the brand's colour tokens"]);
  const bracket = lint(withClass("mt-6 text-[#fff]"));
  assert.ok(bracket.includes('class "text-[#fff]" is a custom colour, type or corner value; use the brand\'s tokens'), bracket.join("; "));
  const template = lint(EXAMPLE.replace('className="mt-6 font-body text-body text-ink-secondary"', 'className={`x ${props.quote ? "bg-[#000]" : ""}`}'));
  assert.ok(template.includes("colour value #000; use the brand's colour tokens"), template.join("; "));
});

test("motion classes are still refused wherever className holds them", () => {
  const options = lintOptionsFor(kitBrand("probe.minted"));
  const at = 'className="mt-6 font-body text-body text-ink-secondary"';
  const forms: [string, string[]][] = [
    ['className={`mt-6 font-body ${props.quote ? "transition duration-300" : ""} ease-in-out`}', ["transition", "duration-300", "ease-in-out"]],
    ['className={["mt-6", props.quote && "animate-spin"].filter(Boolean).join(" ")}', ["animate-spin"]],
  ];
  for (const [className, refused] of forms) {
    const errors = lint(EXAMPLE.replace(at, className), options);
    for (const cls of refused) assert.ok(errors.some((e) => e.startsWith(`class "${cls}" is motion of your own`)), `${cls}: ${errors.join("; ")}`);
  }
});

// Publishing live sites, phase 1 (Task 9): in a live workspace a section runs in the visitor's
// browser, so the check's `interactive` mode allows state, effects, handlers, timers and page reads.
const interactive = { interactive: true } as const;
const section = (body: string, imports = "") => `import { z } from "zod";\n${imports}import type { Kit } from "@/puck/agent-kit";\nexport const schema = z.object({ id: z.string(), surface: z.string() }).strict();\n${body}\nexport function render(props: z.infer<typeof schema>, kit: Kit) { return <kit.Shell surface={props.surface}><Inner /></kit.Shell>; }\n`;

test("interactive: state, effects, handlers, timers and page reads are allowed", () => {
  const source = section(
    `function Inner() {
  const [open, setOpen] = useState(false);
  useEffect(() => { const t = setTimeout(() => setOpen(true), 10); const w = window.innerWidth; void w; return () => clearTimeout(t); }, []);
  return <button className="font-body text-body" onClick={() => setOpen(!open)} aria-expanded={open}>Toggle</button>;
}`,
    'import { useEffect, useState } from "react";\n',
  );
  assert.deepEqual(lint(source, interactive), []);
  assert.ok(lint(source).some((e) => e.includes('"onClick" is an event handler')), "static mode is unchanged");
});

test("interactive: eval, Function, raw HTML, cookies, dynamic import and foreign elements are still refused", () => {
  for (const [code, expected] of [
    ["eval('1')", '"eval"'],
    ["new Function('return 1')", '"Function"'],
    ["document.cookie", '"cookie"'],
    ["import('x')", '"import("'],
  ] as const) {
    const errors = lint(section(`function Inner() { ${code}; return null; }`), interactive);
    assert.ok(errors.some((e) => e.includes(expected)), `${code}: ${JSON.stringify(errors)}`);
  }
  for (const tag of ["script", "iframe", "form", "object", "embed"]) {
    const errors = lint(section(`function Inner() { return <${tag} />; }`), interactive);
    assert.ok(errors.some((e) => e.includes(`<${tag}>`)), tag);
  }
  const raw = lint(section(`function Inner() { return <div dangerouslySetInnerHTML={{ __html: "x" }} />; }`), interactive);
  assert.ok(raw.some((e) => e.includes("dangerouslySetInnerHTML")));
});

test("interactive: a raw <a> is still refused", () => {
  const errors = lint(section(`function Inner() { return <a href="/x">x</a>; }`), interactive);
  assert.ok(errors.includes(LINK_REFUSAL), errors.join("; "));
});

test("static mode is exactly as before: foreign elements are not refused by the check (publish strips them)", () => {
  for (const tag of ["script", "iframe", "form", "object", "embed"]) {
    assert.deepEqual(lint(section(`function Inner() { return <${tag} />; }`)), [], tag);
  }
});

test("the live skill's accordion passes interactive mode with Garner's options", () => {
  const accordion = section(
    `function Inner() {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-line-subtle">
      <button className="font-body text-body text-ink-primary" onClick={() => setOpen(!open)} aria-expanded={open}>Question</button>
      {open ? <p className="mt-4 font-body text-body text-ink-secondary">Answer</p> : null}
    </div>
  );
}`,
    'import { useState } from "react";\n',
  );
  assert.deepEqual(lint(accordion, { ...lintOptionsFor(kitBrand("garner")), interactive: true }), []);
});
