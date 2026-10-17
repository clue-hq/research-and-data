import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { buildSync } from "esbuild";

// Plan 3, Task 6: a selected button shows the mockup's sections in order — Typography (its words,
// with a Text row), Fill, Stroke, Layout, Link (R8 layout), Layers. Render the real inspector (CSS
// modules bundled in memory) over a button binding and read its markup.
const bundle = buildSync({
  stdin: {
    contents: `import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { SiteInspector } from "./site-inspector";
      export const render = (binding) => renderToStaticMarkup(createElement(SiteInspector, { binding }));`,
    resolveDir: fileURLToPath(new URL(".", import.meta.url)),
  },
  bundle: true, write: false, jsx: "automatic", platform: "node", format: "cjs", packages: "external",
  outfile: "site-inspector-button-test.cjs", logLevel: "silent",
});
const renderedModule = { exports: {} as { render: (binding: Record<string, unknown>) => string } };
runInNewContext(bundle.outputFiles[0].text, { module: renderedModule, exports: renderedModule.exports, require: createRequire(import.meta.url), URL });

const noop = () => null;
const TYPO = { color: "#FFFFFF", fontFamily: "Inter", fontSize: 16, fontWeight: 600, italic: false, underline: false, textAlign: "left" };
const box = { fill: "#0F59B0", borderColor: "", borderWidth: 0, radius: [6, 6, 6, 6], paddingY: 12, paddingX: 22, width: 214 };

function buttonBinding(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    disabled: false, error: null, fields: null, layers: [], note: null, onCommit: noop, onSelectLayer: noop, selectionKey: "cta:button", title: "Button", values: null,
    element: {
      key: "button", kind: "button", label: "Request the analysis", computed: TYPO,
      labelElement: { key: "button.label", computed: TYPO, rich: { prop: "buttonLabel" } }, box, labelSource: { kind: "prop", prop: "buttonLabel" }, words: null,
      link: { source: { kind: "prop", href: "buttonHref", newTab: "buttonNewTab" }, href: "/analysis" },
    },
    elementOverride: { radius: "pill" }, onStyleCommit: noop, palette: [{ label: "surface.brand", value: "#014036" }], fonts: [{ family: "Inter", weights: [400, 600, 700] }],
    wordsOverride: null, onWordStyleCommit: noop, wordsUnavailable: null,
    labelOverride: null, labelWordsOverride: null, labelText: "Request the analysis", onLabelTextCommit: noop, onLabelWordStyleCommit: noop,
    linkState: { kind: "link", href: "/analysis", newTab: true, removable: false, shared: false },
    pages: [{ route: "/", title: "Home" }, { route: "/analysis", title: "The analysis" }], onLinkCommit: noop,
    ...overrides,
  };
}

const order = (html: string, labels: string[]) => labels.map((label) => html.indexOf(label));

test("a button shows Typography with its words, then Fill, Stroke, Layout and Link", () => {
  const html = renderedModule.exports.render(buttonBinding());
  const at = order(html, [">Typography<", 'aria-label="Button text"', ">Fill<", ">Stroke<", ">Layout<", ">Link<", ">Layers<"]);
  assert.ok(at.every((index) => index >= 0), JSON.stringify(at));
  assert.deepEqual([...at].sort((a, b) => a - b), at, "in the mockup's order");
  assert.match(html, /value="Request the analysis"/);
  assert.doesNotMatch(html, />Alignment</, "a button's words have no alignment of their own");
  assert.match(html, /also holds when the button is hovered or focused/);
});

test("the corner radius shows Pill chosen; Link takes the R8 layout with the page and New tab chosen", () => {
  const html = renderedModule.exports.render(buttonBinding());
  assert.match(html, /aria-label="Corner radius"/);
  assert.match(html, /aria-pressed="true"[^>]*>Pill</);
  assert.match(html, /aria-pressed="true"[^>]*>Page on this site</);
  assert.match(html, /aria-pressed="true"[^>]*>New tab</);
  assert.match(html, /The analysis \(\/analysis\)/);
});

test("words that cannot be changed here say why instead of a Text box", () => {
  const html = renderedModule.exports.render(buttonBinding({
    labelText: null,
    element: { ...(buttonBinding().element as object), labelSource: { kind: "fixed", reason: "Ask the agent to change these words." } },
  }));
  assert.doesNotMatch(html, /aria-label="Button text"/);
  assert.match(html, /Ask the agent to change these words\./);
});
