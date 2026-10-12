import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { surfaceChoices, surfaceClass } from "@clue/site-kit";
import { kitBrand } from "../../site-kit/test/fixtures/kits";
import { IMPORT_MAP, compileStyles, pageHtml, shimSource } from "../scripts/build";
import { buildPageConfig } from "../src/client/config";

test("the stylesheet carries the brand-token utilities site-kit's sections use, and Puck's own styles", async () => {
  const css = await compileStyles();
  for (const utility of [".bg-surface-page", ".bg-surface-brand-subtle", ".font-headline", ".text-headline", ".rounded-card", ".text-on-surface-inverse"]) {
    assert.ok(css.includes(utility), utility);
  }
  assert.ok(css.includes("--puck-color-azure-04"), "Puck's stylesheet is bundled");
  assert.ok(css.includes("[data-site-shell-selected]"));
});

test("every surface the dock offers paints on the editor canvas in the brand's colour, its own bands included", async () => {
  // A minted kit: besides the six built-in surfaces it has canvas, elevated, accent and two bands
  // measured from the seller's site, whose classes site-kit names at runtime.
  const brand = kitBrand("garner.minted");
  const Root = buildPageConfig(brand, null, []).root!.render as unknown as ComponentType;
  const styles = [...renderToStaticMarkup(createElement(Root)).matchAll(/<style[^>]*>([^<]*)<\/style>/g)];
  const pageCss = (await compileStyles()) + styles.map((match) => match[1]).join("\n");
  const choices = surfaceChoices(brand);
  assert.ok(choices.some((choice) => choice.value.startsWith("band-")), "the fixture carries band surfaces");
  for (const choice of choices) {
    for (const utility of surfaceClass(choice.value).split(" ")) {
      const property = utility.startsWith("bg-") ? "background-color" : "color";
      const rule = new RegExp(`\\.${utility}\\s*\\{(?:[^}]*?[;\\s])?${property}\\s*:\\s*var\\((--[\\w-]+)\\)`).exec(pageCss);
      assert.ok(rule, `${choice.label} (${choice.value}): no ${property} rule for .${utility}`);
      assert.ok(pageCss.includes(`${rule[1]}:`), `${choice.label}: .${utility} paints with ${rule[1]}, which the brand never defines`);
    }
  }
});

test("each shim re-exports the editor's own copy and fails loudly before it is shared", () => {
  const source = shimSource("react", ["useState", "useEffect"]);
  assert.ok(source.includes('globalThis.__clueSectionHost["react"]'));
  assert.ok(source.includes("export const { useState, useEffect } = m;"));
  assert.ok(source.includes("throw new Error"));
});

test("the page has exactly one inline script — the nonced import map — and the bundle", () => {
  const html = pageHtml("editor-1.js", "editor-1.css");
  assert.equal(html.match(/<script/g)?.length, 2);
  assert.ok(html.includes(`<script type="importmap" nonce="%NONCE%">${IMPORT_MAP}</script>`));
  assert.ok(html.includes('<script type="module" src="/assets/editor-1.js"></script>'));
  assert.ok(html.includes('<meta name="clue-app-origin" content="%APP_ORIGIN%">'));
  assert.deepEqual(JSON.parse(IMPORT_MAP).imports, {
    react: "/shims/react.mjs",
    "react/jsx-runtime": "/shims/react-jsx-runtime.mjs",
    zod: "/shims/zod.mjs",
  });
});
