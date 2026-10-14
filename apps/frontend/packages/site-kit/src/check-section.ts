// The check a section written by the agent must pass before it joins its site (E5).
//
// Usage: npx tsx src/check-section.ts <file.tsx>
// Prints {"ok": bool, "errors": [...]} as JSON.
//
// Structure is free; style is the brand's. Refused: colour values where a colour can apply (a
// className, an SVG colour attribute; prose is never read for them), Tailwind's own palette colours,
// Tailwind's default type sizes, families and weights, bracketed custom values for colour, type
// or corners (layout measures such as max-w-[30ch] are fine), inline styles, imports other than
// zod, react types and the kit, and the banned names below (page globals, network, eval, raw
// HTML, storage, timers, event handlers). The file must export `schema` (a zod object) and
// `render`, and must type-check.
//
// Interactive mode (publishing live sites, founder 2026-10-15; `LintOptions.interactive`, passed for
// a workspace whose sites publish live): the section runs in the visitor's browser, so state,
// effects, event handlers, timers and page reads are allowed. Still refused there: eval and
// Function, raw HTML, cookies, dynamic import, a raw <a>, and the foreign elements <script>,
// <iframe>, <form>, <object> and <embed>. Without the option the check is exactly the static one.
//
// D2 (founder, 2026-10-09 and 2026-10-11): this check NEVER imports the section. The props schema,
// and the rules about it (an id and a surface, no className or style), are read inside the design
// API's hardened render page (lumen_api.site_render.read_section_schema), never in a platform
// process.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import type { BrandData } from "./brand";
import { buttonLooks, cardLooks, motionClassNames } from "./looks";
import { COLOR_ROLES, SURFACES as THEME_SURFACES, colorVar, extraSurfaceRoles } from "./theme";

const ALLOWED_IMPORTS = new Set(["zod", "react", "@/puck/agent-kit"]);
const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const COLOUR_UTILITY = "text|bg|border|fill|stroke|ring|outline|decoration|divide|from|via|to|accent|caret|shadow|placeholder";
const RULES: { pattern: RegExp; why: string }[] = [
  { pattern: new RegExp(`^(${COLOUR_UTILITY})-(${PALETTE})-\\d{2,3}(\\/\\d+)?$`), why: "a Tailwind palette colour; use the brand's text-ink-*, bg-surface-* or border-line-*" },
  { pattern: new RegExp(`^(${COLOUR_UTILITY})-(black|white)(\\/\\d+)?$`), why: "a fixed colour; use the brand's text-ink-*, bg-surface-* or border-line-*" },
  { pattern: /^text-(xs|sm|base|lg|xl|[2-9]xl)$/, why: "a Tailwind type size; use a brand type role (text-title, text-body…)" },
  { pattern: /^font-(sans|serif|mono|thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$/, why: "a Tailwind font or weight; use a brand type role (font-title, font-body…)" },
  { pattern: /^(text|bg|border|fill|stroke|ring|outline|decoration|font|leading|tracking|rounded|shadow|from|via|to)-\[/, why: "a custom colour, type or corner value; use the brand's tokens" },
];

/** A colour class in the brand's own namespaces (text-ink-*, bg-surface-*, text-on-surface-*,
 * border-line-*, ring-focus). Its name must be one the theme defines: issue 49's
 * border-line-inverse and bg-surface-brandSubtle exist nowhere and render unstyled. */
const BRAND_COLOUR_CLASS = new RegExp(`^(?:${COLOUR_UTILITY})-((?:ink|surface|on-surface|line)(?:-[A-Za-z0-9-]+)?|focus)$`);

export const LINK_REFUSAL =
  "<a> is not allowed in a section; write links with kit.Link (or kit.Button for a button) so they reach the right page wherever the site is published";

/** What the brand has, so a section is checked against it (B6 passes lintOptionsFor(brand)).
 * Without a brand only the brand-independent rules run. */
export type LintOptions = { extraSurfaces?: string[]; buttonLooks?: string[]; cardLooks?: string[]; motions?: string[]; interactive?: boolean };

export function lintOptionsFor(brand: BrandData): LintOptions {
  return {
    extraSurfaces: extraSurfaceRoles(brand),
    buttonLooks: buttonLooks(brand).map((look) => look.name),
    cardLooks: cardLooks(brand).map((look) => look.name),
    motions: motionClassNames(brand),
  };
}

function brandColourNames(extraSurfaces: string[]): Set<string> {
  const names = new Set<string>(COLOR_ROLES.map(colorVar));
  for (const surface of [...THEME_SURFACES, ...extraSurfaces]) {
    names.add(colorVar(surface));
    names.add(`on-${colorVar(surface)}`);
  }
  return names;
}

const STATE_VARIANT = /^(hover|focus|focus-visible|focus-within|active|group-hover|group-focus|peer-hover|peer-focus)$/;
const MOTION_UTILITY = /^(transition(-[a-z]+)?|duration-.+|ease-.+|delay-.+|animate-.+)$/;
const STATE_MOTION = /^-?(translate|scale|rotate|skew)(-[xy])?-|^(opacity|shadow|blur|brightness|contrast|saturate|drop-shadow)(-|$)/;

/** The text of every string inside the named JSX attributes: `name="…"`, ``name={`… ${x}`}``,
 * `name={["a", cond && "b"].join(" ")}`. A section's other strings (a schema's description, a
 * default heading, an alt text) are prose and are never read. */
function attributeStrings(source: string, names: ReadonlySet<string>): string[] {
  const file = ts.createSourceFile("section.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const strings: string[] = [];
  const collect = (node: ts.Node) => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) {
      strings.push(node.text);
    }
    ts.forEachChild(node, collect);
  };
  const visit = (node: ts.Node) => {
    if (ts.isJsxAttribute(node) && names.has(node.name.getText(file))) {
      if (node.initializer) collect(node.initializer);
      return;
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return strings;
}

/** The strings inside className attributes. These are classes; no other string counts as one. */
const classNameStrings = (source: string) => attributeStrings(source, new Set(["className"]));

/** Where a colour value can apply in a section: its classes and the SVG colour attributes. An inline
 * style is refused whole, so prose (text, alt, title, a schema's defaults) is never read for colours. */
const COLOUR_ATTRIBUTES: ReadonlySet<string> = new Set([
  "className", "fill", "stroke", "color", "stopColor", "stop-color", "floodColor", "flood-color", "lightingColor", "lighting-color",
]);

/** An inline style in the code: a JSX `style` attribute (any value), or an object key named `style`
 * (`{ style: … }`, `{ "style": … }`, `{ style }`), which is how React.createElement takes one. Read
 * from the syntax tree, so prose that says "style:" in a string or a template never counts. */
function hasInlineStyle(source: string): boolean {
  const file = ts.createSourceFile("section.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const visit = (node: ts.Node): boolean =>
    (ts.isJsxAttribute(node) && node.name.getText(file) === "style") ||
    ((ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node)) &&
      (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)) &&
      node.name.text === "style") ||
    (ts.forEachChild(node, visit) ?? false);
  return visit(file);
}

/** Every literal look on a kit.Button or kit.Card: `look="x"`, `look={"x"}`, ``look={`x`}``. A look
 * the section computes (`look={props.look}`, a template with `${}`) is props data; the validator
 * checks that. */
function kitLooks(source: string): { component: "Button" | "Card"; look: string }[] {
  const file = ts.createSourceFile("section.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const looks: { component: "Button" | "Card"; look: string }[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(file);
      if (tag === "kit.Button" || tag === "kit.Card") {
        for (const attribute of node.attributes.properties) {
          if (!ts.isJsxAttribute(attribute) || attribute.name.getText(file) !== "look") continue;
          const value = attribute.initializer && ts.isJsxExpression(attribute.initializer) ? attribute.initializer.expression : attribute.initializer;
          if (value && (ts.isStringLiteral(value) || ts.isNoSubstitutionTemplateLiteral(value))) {
            looks.push({ component: tag === "kit.Button" ? "Button" : "Card", look: value.text });
          }
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return looks;
}

/** Class tokens with their variants (`group-hover:-translate-y-1` → variants ["group-hover"]). */
function variantTokens(strings: string[]): { token: string; base: string; variants: string[] }[] {
  return strings.flatMap((s) => s.split(/\s+/)).filter(Boolean).map((token) => {
    const parts = token.split(":");
    return { token, base: parts[parts.length - 1], variants: parts.slice(0, -1) };
  });
}

// D2 spike (Task 4): names a section may not use, wherever they appear in its code (a variable, a
// property such as document.cookie, an object key). Read from the syntax tree, so the words in a
// section's text or strings never count. A guardrail against the obvious, not a sandbox: the
// hardened render page is the boundary (trials/puck-spike/RUNTIME-SECTIONS.md).
const BANNED: Record<string, string> = {
  window: "reaches the page outside the section",
  document: "reaches the page outside the section",
  globalThis: "reaches the page outside the section",
  fetch: "is a network call",
  XMLHttpRequest: "is a network call",
  WebSocket: "is a network call",
  eval: "runs code the check never saw",
  Function: "runs code the check never saw",
  dangerouslySetInnerHTML: "writes raw HTML",
  localStorage: "reads the visitor's storage",
  cookie: "reads the visitor's cookies",
  setTimeout: "is a timer; a section renders once from its props",
  setInterval: "is a timer; a section renders once from its props",
};

/** In a live workspace a section runs in the visitor's browser (publishing live sites, founder
 * 2026-10-15): it may keep state, handle events, run effects and timers and read the page. Where it
 * can send data is the published page's policy's job, not this check's. What stays refused has its
 * own reason, below. */
const INTERACTIVE_BANNED: Record<string, string> = {
  eval: "runs code the check never saw",
  Function: "runs code the check never saw",
  dangerouslySetInnerHTML: "writes raw HTML",
  cookie: "reads or sets cookies; a section keeps its state in React or in localStorage",
};
/** Elements an interactive section may not render. Interactive mode only: in static mode the check
 * is unchanged and publish strips them, as before. */
const FOREIGN_ELEMENTS: Record<string, string> = {
  script: "<script> is not allowed in a section; its code is the section itself",
  iframe: "<iframe> is not allowed in a section",
  form: "<form> is not allowed in a section",
  object: "<object> is not allowed in a section",
  embed: "<embed> is not allowed in a section",
};

function bannedNames(source: string, interactive = false): string[] {
  const banned = interactive ? INTERACTIVE_BANNED : BANNED;
  const errors: string[] = [];
  const seen = new Set<string>();
  const add = (message: string) => {
    if (!seen.has(message)) {
      seen.add(message);
      errors.push(message);
    }
  };
  const file = ts.createSourceFile("section.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const visit = (node: ts.Node) => {
    if (ts.isIdentifier(node) && Object.hasOwn(banned, node.text)) {
      add(interactive ? `"${node.text}" ${banned[node.text]}` : `"${node.text}" ${banned[node.text]}; a section renders its props and nothing else`);
    }
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      add(interactive ? `"import(" loads code the check never saw` : `"import(" loads code the check never saw; a section renders its props and nothing else`);
    }
    // An event handler, as a JSX prop or as a key of an object that might be spread into one.
    if (!interactive && (ts.isJsxAttribute(node) || ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node) || ts.isMethodDeclaration(node))) {
      const name = node.name.getText(file).replace(/^["'`]|["'`]$/g, "");
      if (/^on[A-Z]/.test(name)) add(`"${name}" is an event handler; a section is static`);
    }
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(file);
      if (tag === "a") add(LINK_REFUSAL);
      if (interactive && Object.hasOwn(FOREIGN_ELEMENTS, tag)) add(FOREIGN_ELEMENTS[tag]);
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return errors;
}

function classTokens(source: string): string[] {
  const strings = [...source.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g)].map((m) => m[1] ?? m[2] ?? m[3] ?? "");
  return strings.flatMap((s) => s.split(/\s+/)).filter(Boolean).map((t) => t.split(":").pop() ?? t);
}

export function lint(source: string, options: LintOptions = {}): string[] {
  const errors: string[] = [];
  for (const m of source.matchAll(/import\s+(?:type\s+)?[^"']*from\s+["']([^"']+)["']/g)) {
    if (!ALLOWED_IMPORTS.has(m[1])) errors.push(`import "${m[1]}" is not allowed; a section imports only zod, react types and @/puck/agent-kit`);
  }
  const colourStrings = attributeStrings(source, COLOUR_ATTRIBUTES);
  for (const text of colourStrings) {
    for (const m of text.matchAll(/#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/g)) errors.push(`colour value ${m[0]}; use the brand's colour tokens`);
  }
  for (const text of colourStrings) {
    for (const m of text.matchAll(/\b(rgba?|hsla?|oklch|oklab|lab|lch)\(/g)) errors.push(`colour function ${m[0]}…); use the brand's colour tokens`);
  }
  if (hasInlineStyle(source)) errors.push("inline style; style only with the brand's classes");
  const seen = new Set<string>();
  for (const token of classTokens(source)) {
    for (const rule of RULES) {
      if (rule.pattern.test(token) && !seen.has(token)) {
        seen.add(token);
        errors.push(`class "${token}" is ${rule.why}`);
      }
    }
  }
  const known = brandColourNames(options.extraSurfaces ?? []);
  for (const token of classTokens(source)) {
    const bare = token.replace(/^!/, "").replace(/\/\d+$/, "");
    const match = BRAND_COLOUR_CLASS.exec(bare);
    if (match && !known.has(match[1]) && !seen.has(token)) {
      seen.add(token);
      errors.push(`class "${token}" is not one of the brand's classes; the brand's colour classes are text-ink-*, bg-surface-*, text-on-surface-* and border-line-* (see brand/brand.md)`);
    }
  }
  errors.push(...bannedNames(source, options.interactive === true));
  if (!/export\s+const\s+schema\b/.test(source)) errors.push("the file must export `schema` (a zod object of the section's props)");
  if (!/export\s+function\s+render\b/.test(source)) errors.push("the file must export `function render(props, kit)`");
  for (const { token, base, variants } of variantTokens(classNameStrings(source))) {
    if (seen.has(token)) continue;
    const ownMotion = MOTION_UTILITY.test(base) || (variants.some((v) => STATE_VARIANT.test(v)) && STATE_MOTION.test(base));
    if (ownMotion) {
      seen.add(token);
      errors.push(`class "${token}" is motion of your own; motion comes from the brand: kit.Button, kit.Link and kit.Card carry it, and a class from brand/brand.md (Motion) adds it to an element`);
    } else if (options.motions && /^brand-motion-/.test(base) && !options.motions.includes(base)) {
      seen.add(token);
      errors.push(`class "${token}" is not one of this brand's motion classes; its motion classes are ${options.motions.join(", ") || "none"} (brand/brand.md, Motion)`);
    }
  }
  for (const { component, look } of kitLooks(source)) {
    const known = component === "Button" ? options.buttonLooks : options.cardLooks;
    if (known && !known.includes(look)) {
      errors.push(component === "Button"
        ? `look "${look}" on kit.Button is not one of this brand's button styles; the styles are ${known.join(", ") || "none"} (brand/brand.md, Buttons)`
        : `look "${look}" on kit.Card is not one of this brand's card styles; the styles are ${known.join(", ") || "none"} (brand/brand.md, Cards)`);
    }
  }
  return errors;
}

export function typeCheck(file: string): string[] {
  const dir = path.dirname(file);
  // The package's tsconfig maps the kit's import (@/puck/agent-kit) to src/agent-kit.tsx. The file
  // must sit where zod and react resolve (inside apps/frontend), as in the spike.
  const root = fileURLToPath(new URL("..", import.meta.url));
  const tsc = createRequire(import.meta.url).resolve("typescript/bin/tsc");
  fs.writeFileSync(
    path.join(dir, "tsconfig.json"),
    JSON.stringify({
      extends: path.relative(dir, path.join(root, "tsconfig.json")),
      compilerOptions: { incremental: false, noEmit: true },
      include: [path.basename(file)],
      // Inheriting an exclude that covers the file's directory would silently type-check nothing.
      exclude: [],
    }),
  );
  try {
    execFileSync(process.execPath, [tsc, "-p", path.join(dir, "tsconfig.json")], { cwd: root, stdio: "pipe" });
    return [];
  } catch (error) {
    const out = String((error as { stdout?: Buffer }).stdout ?? error);
    return out.split("\n").filter((l) => l.includes("error TS")).slice(0, 8).map((l) => `type error: ${l.replace(/^.*?\(/, "(")}`);
  }
}

function main() {
  const file = path.resolve(process.argv[2] ?? "");
  const source = fs.readFileSync(file, "utf-8");
  const errors = lint(source);
  if (!errors.length) errors.push(...typeCheck(file));
  console.log(JSON.stringify({ ok: errors.length === 0, errors }));
}

if (process.argv[1]?.endsWith("check-section.ts")) main();
