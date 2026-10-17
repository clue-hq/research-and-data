// No component in site-kit carries a style value of its own (founder, 2026-10-12): every class in a
// component file is structure (layout) or the brand's (theme.ts and its Tailwind mapping), and the
// only literal colours and lengths in site-kit are its named FALLBACKS (src/brand-values.ts).
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

const read = (file: string) => fs.readFileSync(new URL(`../src/${file}`, import.meta.url), "utf-8");
const COMPONENTS = ["sections.tsx", "shell.tsx", "agent-kit.tsx", "config.tsx"];
const GENERATORS = ["theme.ts", "looks.ts", "surfaces.ts", "brand-values.ts"];

/** Layout: where things go, never how the brand looks. */
const STRUCTURE = [
  /^(flex|inline-flex|grid|block|inline-block|inline|hidden|contents)$/,
  /^flex-(row|col|wrap|1|none)$/, /^(grow|shrink-0|min-w-0)$/, /^self-(start|center|end)$/,
  /^grid-cols-(\d+|\[[0-9a-z(),_.]+\])$/, /^order-\d+$/,
  /^items-(start|center|end|baseline|stretch)$/, /^justify-(start|center|end|between)$/,
  /^text-(left|center|right)$/, /^(truncate|whitespace-nowrap|sr-only)$/,
  /^(w|h)-(full|auto)$/, /^max-w-\[\d+ch\]$/, /^mx-auto$/,
  /^(relative|absolute|inset-0|overflow-hidden)$/, /^object-(cover|contain)$/,
  /^\[&>\*\]:mx-auto$/, /^\[&_dd\]:mx-auto$/,
  /^lumen-fragment$/, // a clone's wrapper: its own captured CSS styles it
  /^clue-section$/, // the box that scopes a section's manual styling: display:contents, no box of its own
];
/** The brand's: theme.ts classes and the Tailwind names mapped to kit values. */
const BRAND = [
  /^brand-[a-z0-9-]+$/, /^(bg-surface|text-on-surface)-[a-z0-9-]*$/, /^text-ink-[a-z]+$/,
  /^(font|text)-(display|headline|title|subtitle|body|body-small|eyebrow|cta|stat|label|caption|legal)$/,
  /^rounded-(none|xs|sm|md|lg|xl|card|button|badge|full)$/,
  /^(m|p)[xytrbl]?-(section|page-margin|stack-tight|stack-default|stack-loose|card-padding)$/,
  /^gap(-[xy])?-(section|page-margin|stack-tight|stack-default|stack-loose|card-padding)$/,
];
const RESPONSIVE = /^(sm|md|lg|xl|2xl):/;
const CLASS_TOKEN = /^[a-z0-9!\[\]&>*_:/.()%,-]+$/;

function strings(source: string): string[] {
  return [...source.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g)].flatMap((m) => (m[1] ?? m[2] ?? m[3] ?? "").split(/\$\{[^}]*\}/));
}

/** Every token of every string that reads as a class list (lower-case, hyphenated, no paths). */
function classTokens(source: string): string[] {
  return strings(source).flatMap((text) => {
    const tokens = text.split(/\s+/).filter(Boolean);
    const classLike = tokens.length > 0
      && tokens.every((t) => CLASS_TOKEN.test(t) && !t.startsWith("/") && !t.startsWith(".") && !t.startsWith("#") && !t.includes("//"))
      && tokens.some((t) => t.includes("-") || t.includes(":"));
    return classLike ? tokens : [];
  });
}

const allowed = (token: string) => [...STRUCTURE, ...BRAND].some((pattern) => pattern.test(token.replace(RESPONSIVE, "")));

test("every class in a component file is structure or the brand's", () => {
  const offenders = COMPONENTS.flatMap((file) => classTokens(read(file)).filter((t) => !allowed(t)).map((t) => `${file}: ${t}`));
  assert.deepEqual(offenders, []);
  assert.ok(classTokens(read("sections.tsx")).length > 40, "the scan sees the sections' classes");
});

test("no component writes an inline style, a colour or an arrow of its own", () => {
  for (const file of COMPONENTS) {
    const source = read(file);
    assert.doesNotMatch(source, /\bstyle=\{/, file);
    assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/, file);
    assert.doesNotMatch(source, /→/, `${file}: an arrow is the seller's icon or the agent's words`);
  }
});

test("the only literal colours and lengths in site-kit are its named fallbacks", () => {
  const value = /(^|[^\w$])\d+(\.\d+)?(px|rem|em)\b|#[0-9a-fA-F]{3,8}\b|rgba?\(/;
  for (const file of GENERATORS) {
    let source = read(file);
    if (file === "brand-values.ts") source = source.replace(/export const FALLBACKS = \{[\s\S]*?\} as const;/, "");
    assert.deepEqual(strings(source).filter((text) => value.test(text)), [], file);
  }
});
