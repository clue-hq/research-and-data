// Lane B Task 15 (Contract 4): an agent-written section is checked, bundled and given its
// Tailwind theme in Node, and never imported (D2).
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { compileSection, HOST_SPECIFIERS } from "../bin/compile-section";
import { garner } from "./fixtures/garner";

// The spike's writing-a-section example, verbatim (the check-section tests use the same file).
const EXAMPLE = fs.readFileSync(new URL("./fixtures/section-example.tsx", import.meta.url), "utf-8");
const CHECK_DIR = new URL("../.section-check/", import.meta.url);

test("a valid section compiles to a module that imports only what the host provides", async () => {
  const result = await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  assert.equal(result.ok, true, JSON.stringify(result));
  if (!result.ok) return;
  const imports = [...result.moduleJs.matchAll(/(?:^|\n)\s*import\s[^"']*["']([^"']+)["']/g)].map((m) => m[1]);
  assert.ok(imports.every((specifier) => (HOST_SPECIFIERS as readonly string[]).includes(specifier)), imports.join(", "));
  assert.match(result.moduleJs, /export\s*\{/);
  assert.ok(result.tailwindTheme.startsWith("@theme inline {"));
});

test("the same source compiles to the same bytes, so the digest is the content's", async () => {
  const a = await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  const b = await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  assert.ok(a.ok && b.ok);
  if (a.ok && b.ok) assert.equal(a.moduleJs, b.moduleJs);
});

test("a brand-token error is refused before the type check runs", async () => {
  const source = EXAMPLE.replace("mt-6 font-body text-body text-ink-secondary", "mt-6 text-emerald-600");
  const result = await compileSection({ name: "QuoteBand", source, brand: garner() });
  assert.equal(result.ok, false);
  if (!result.ok) assert.ok(result.errors.some((e) => e.includes('class "text-emerald-600"')), result.errors.join("; "));
});

test("a type error is refused", async () => {
  const source = EXAMPLE.replace("export function render", 'const wrong: number = "seven";\nexport function render');
  const result = await compileSection({ name: "QuoteBand", source, brand: garner() });
  assert.equal(result.ok, false);
  if (!result.ok) assert.ok(result.errors.some((e) => e.startsWith("type error:")), result.errors.join("; "));
});

test("a bad name is refused and the check folder is left empty", async () => {
  const result = await compileSection({ name: "quoteBand", source: EXAMPLE, brand: garner() });
  assert.deepEqual(result, { ok: false, name: "quoteBand", errors: ['section name "quoteBand" is not PascalCase letters and digits'] });
  await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  const left = fs.existsSync(CHECK_DIR) ? fs.readdirSync(CHECK_DIR).filter((entry) => entry.length === 36) : [];
  assert.deepEqual(left, []);
});

test("K2-1: a section importing a name react does not export is refused at write time", async () => {
  const source = fs.readFileSync(new URL("./fixtures/section-example.tsx", import.meta.url), "utf-8")
    .replace('import { z } from "zod";', 'import { z } from "zod";\nimport { useNotAHook } from "react";\nvoid useNotAHook;');
  const result = await compileSection({ name: "QuoteBand", source, brand: garner() });
  assert.equal(result.ok, false);
  // The type check refuses the missing name before the bundle's named-import check gets to it;
  // either message is the refusal that matters.
  assert.ok(
    !result.ok && result.errors.some((e) => e.includes('"useNotAHook" from "react"') || e.includes("no exported member 'useNotAHook'")),
    JSON.stringify(result),
  );
});

test("K2-1: a section importing a real react export the editor's old hand-written list lacked compiles", async () => {
  const source = fs.readFileSync(new URL("./fixtures/section-example.tsx", import.meta.url), "utf-8")
    .replace('import { z } from "zod";', 'import { z } from "zod";\nimport { cache } from "react";\nvoid cache;');
  const result = await compileSection({ name: "QuoteBand", source, brand: garner() });
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.ok(result.ok && /import\s*\{[^}]*\bcache\b[^}]*\}\s*from\s*"react"/.test(result.moduleJs), result.ok ? result.moduleJs : "");
});

// Publishing live sites, phase 1 (Task 9): a live workspace compiles with `interactive`, so a
// section may keep state and handle events; without it the same source is refused, as today.
const ACCORDION = `import { z } from "zod";
import { useState } from "react";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({ id: z.string(), surface: z.string(), question: z.string(), answer: z.string() }).strict();

function Item(props: { question: string; answer: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-line-subtle">
      <button className="font-body text-body text-ink-primary" onClick={() => setOpen(!open)} aria-expanded={open}>{props.question}</button>
      {open ? <p className="mt-4 font-body text-body text-ink-secondary">{props.answer}</p> : null}
    </div>
  );
}

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <Item question={props.question} answer={props.answer} />
    </kit.Shell>
  );
}
`;

test("interactive: an accordion with state and a click handler compiles; without interactive it is refused", async () => {
  const live = await compileSection({ name: "FaqAccordion", source: ACCORDION, brand: garner(), interactive: true });
  assert.equal(live.ok, true, JSON.stringify(live));
  assert.ok(live.ok && /from\s*"react"/.test(live.moduleJs), live.ok ? live.moduleJs : "");
  const fixed = await compileSection({ name: "FaqAccordion", source: ACCORDION, brand: garner() });
  assert.equal(fixed.ok, false);
  assert.ok(!fixed.ok && fixed.errors.includes('"onClick" is an event handler; a section is static'), JSON.stringify(fixed));
});

test("S2a-2: a section with props marked to edit in place compiles from its own schema, markers kept", async () => {
  const source = EXAMPLE.replace("quote: z.string().min(1),", 'quote: z.string().min(1).meta({ edit: "inline" }),');
  assert.notEqual(source, EXAMPLE);
  const result = await compileSection({ name: "QuoteBand", source, brand: garner() });
  assert.equal(result.ok, true, JSON.stringify(result));
  if (result.ok) {
    assert.match(result.moduleJs, /\.meta\(\{\s*edit:\s*"inline"\s*\}\)/);
    assert.doesNotMatch(result.moduleJs, /custom/);
  }
});
