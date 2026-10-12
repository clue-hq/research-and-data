import assert from "node:assert/strict";
import { test } from "node:test";
import { IMPORT_MAP, compileStyles, pageHtml, shimSource } from "../scripts/build";

test("the stylesheet carries the brand-token utilities site-kit's sections use, and Puck's own styles", async () => {
  const css = await compileStyles();
  for (const utility of [".bg-surface-page", ".bg-surface-brand-subtle", ".font-headline", ".text-headline", ".rounded-card", ".text-ink-inverse"]) {
    assert.ok(css.includes(utility), utility);
  }
  assert.ok(css.includes("--puck-color-azure-04"), "Puck's stylesheet is bundled");
  assert.ok(css.includes("[data-site-shell-selected]"));
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
