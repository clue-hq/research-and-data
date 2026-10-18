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

test("words copied from the seller that also appear elsewhere in the section say so (review 9)", () => {
  const html = renderedModule.exports.render(buttonBinding({
    element: { ...(buttonBinding().element as object), labelSource: { kind: "replacement", find: "Book a demo", shared: true } },
  }));
  assert.match(html, /Other text in this section reads the same, so changing it changes that text too\./);
});

// Plan 4: a box, an image and a section's own box, rendered through the real inspector.
const container = { fill: "#FFFFFF", borderColor: "", borderWidth: 0, radius: [12, 12, 12, 12], paddingY: 24, paddingX: 32, width: 480, gap: 0, layout: "text", contentAlign: "start", name: "Card" };
const plan4 = { arrange: null, onMove: noop, hide: null, onHideCommit: noop, headerPlacement: null, onHeaderPlacementCommit: noop, sectionBox: null, sectionBoxOverrides: { inner: null, outer: null } };

test("a box shows Fill, Stroke, Layout with its gap, and Arrange with Move up/down and content alignment", () => {
  const html = renderedModule.exports.render(
    buttonBinding({
      ...plan4,
      element: { key: "stats.1", kind: "container", label: "Card", computed: TYPO, container, arrange: { item: "stats.1", parent: "stats", siblings: ["stats.0", "stats.1"] } },
      elementOverride: null,
      arrange: { canUp: true, canDown: false, note: null },
      title: "Card",
    }),
  );
  const at = order(html, [">Fill<", ">Stroke<", ">Layout<", ">Gap<", ">Arrange<", "Move up", "Content alignment", ">Layers<"]);
  assert.ok(at.every((index) => index >= 0), JSON.stringify(at));
  assert.deepEqual([...at].sort((a, b) => a - b), at, "in the mockup's order");
  assert.doesNotMatch(html, />Typography</, "a box has no typography rows");
  assert.match(html, /gap applies to rows and grids/, "a block box says why its gap is off");
  assert.doesNotMatch(html, /hovered or focused/);
});

test("a fixed part says why it does not move; a hidden header part offers Shown / Hidden", () => {
  const html = renderedModule.exports.render(
    buttonBinding({
      ...plan4,
      element: { key: "logo", kind: "image", label: "Logo", computed: TYPO, image: { media: "img", box, fit: null, fitMatters: false, alt: "", src: "/brands/logo.png" }, imageSource: { kind: "fixed", reason: "The seller's logo comes from the brand kit." }, altSource: { kind: "prop", prop: "logoAlt" } },
      arrange: { canUp: false, canDown: false, note: "This part's place is set by the section's design; ask the agent to move it." },
      hide: { hidden: true, part: "header" },
      imageAlt: "", onImageAltCommit: noop, imageReplace: null,
    }),
  );
  // Plan 5: the seller's logo cannot be replaced here; its alt text can.
  assert.match(html, /The seller&#x27;s logo comes from the brand kit\./);
  assert.match(html, /aria-label="Alt text"/);
  assert.match(html, /This part&#x27;s place is set by the section&#x27;s design/);
  assert.match(html, /aria-label="Show in the header"/);
  assert.match(html, />Hidden</);
});

test("a selected section shows its Content, then its own box with Width off", () => {
  const html = renderedModule.exports.render(
    buttonBinding({
      ...plan4,
      element: null,
      fields: [{ name: "heading", label: "Heading", kind: "text" }],
      values: { heading: "H" },
      sectionBox: { outer: { key: "root", box }, inner: { key: "root.inner", container } },
    }),
  );
  const at = order(html, [">Content<", ">Fill<", ">Layout<", "A section always spans the page.", "Content alignment"]);
  assert.ok(at.every((index) => index >= 0), JSON.stringify(at));
  assert.deepEqual([...at].sort((a, b) => a - b), at);
  assert.doesNotMatch(html, /Move up/, "a section does not move here");
});

// Plan 5: the image panel.
const picture = { media: "img", box, fit: "fill", fitMatters: true, alt: "A room", src: "/brands/x.png" };
const imageBinding = (overrides: Record<string, unknown> = {}) =>
  buttonBinding({
    ...plan4,
    element: { key: "image", kind: "image", label: "Image", computed: TYPO, image: picture, imageSource: { kind: "prop", prop: "image", uses: 1 }, altSource: { kind: "prop", prop: "imageAlt" } },
    elementOverride: null, values: { image: "/brands/x.png" }, imageAlt: "A room", onImageAltCommit: noop, imageReplace: { prop: "image", uses: 1 },
    ...overrides,
  });

test("an image shows Image, Fit, Alt text, Stroke, Arrange and Layers in order", () => {
  const html = renderedModule.exports.render(imageBinding({ arrange: { canUp: true, canDown: true, note: null } }));
  const at = order(html, [">Image<", ">Fit<", ">Alt text<", ">Stroke<", ">Arrange<", ">Layers<"]);
  assert.ok(at.every((index) => index >= 0), JSON.stringify(at));
  assert.deepEqual([...at].sort((a, b) => a - b), at, "in the mockup's order");
  assert.equal((html.match(/aria-label="Color opacity"/g) ?? []).length, 1, "only Stroke's colour: an image has no Fill");
  assert.doesNotMatch(html, /Padding top and bottom/, "an image has no Layout");
  assert.match(html, /value="A room"/);
});

test("fit is off with its note when the shape does not change it; a shared picture says how many it changes", () => {
  const html = renderedModule.exports.render(imageBinding({ element: { key: "image", kind: "image", label: "Image", computed: TYPO, image: { ...picture, fitMatters: false }, imageSource: { kind: "slot", slot: "hero", uses: 2 }, altSource: { kind: "clone", key: "0.1" } }, imageReplace: { prop: "slots.hero", uses: 2 } }));
  assert.match(html, /This image is shown at its own shape, so Fill and Fit look the same here\./);
  assert.match(html, /This picture appears 2 times on this section; replacing it changes all of them\./);
});

test("a video shows its notes for Replace and Alt text, and keeps Fit and Stroke", () => {
  const html = renderedModule.exports.render(imageBinding({
    element: { key: "0.3", kind: "image", label: "Image", computed: TYPO, image: { ...picture, media: "video" }, imageSource: { kind: "fixed", reason: "Ask the agent to change a video." }, altSource: { kind: "fixed", reason: "Videos have no alt text; the agent can describe one in the words beside it." } },
    imageAlt: null, imageReplace: null,
  }));
  assert.match(html, /Ask the agent to change a video\./);
  assert.match(html, /Videos have no alt text/);
  assert.match(html, />Fit</);
  assert.match(html, />Stroke</);
});

// Founder 2026-10-19: Arrange's Order row looks like the ad editor's Layer row — icon buttons in the
// same grid, named by their aria-label, a disabled one dimmed.
test("Arrange's Order row is the ad editor's icon row: Move up and Move down as icon buttons", () => {
  const html = renderedModule.exports.render(
    buttonBinding({
      ...plan4,
      element: { key: "stats.1", kind: "container", label: "Card", computed: TYPO, container, arrange: { item: "stats.1", parent: "stats", siblings: ["stats.0", "stats.1"] } },
      elementOverride: null,
      arrange: { canUp: true, canDown: false, note: null },
      title: "Card",
    }),
  );
  assert.doesNotMatch(html, /↑|↓/, "no arrow glyph words");
  assert.match(html, /aria-label="Move up"[^>]*>.*?layer-up/s);
  assert.match(html, /aria-label="Move down"[^>]*disabled=""[^>]*>.*?layer-down/s);
  assert.match(html, /grid-template-columns:repeat\(2, minmax\(0, 1fr\)\)/);
});
