import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "@clue/site-kit";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import { cloneLabelsOf, componentLabel, siteLayerRows, layerListHeight } from "./site-layers";

const site = SiteDocumentSchema.parse({
  id: "doc-a",
  title: "A",
  theme: {},
  pages: {
    "/": {
      root: { props: { title: "Garner for SCSD" } },
      content: [
        { type: "ClonedSection", props: { id: "hero", fragmentId: "frag_95041c54da629d99" } },
        { type: "StatsBand", props: { id: "proof", heading: "7.4%" } },
        { type: "AnalysisSteps", props: { id: "steps" } },
      ],
    },
  },
  // Plan 6: the header is a template (a copied section), the footer the fallback.
  shell: {
    header: { type: "ClonedSection", props: { id: "header", fragmentId: "frag_95041c54da629d99" } },
    footer: { type: "SiteFooter", props: { id: "footer", legal: "©" } },
  },
  agent_sections: { AnalysisSteps: "a".repeat(64) },
});
const cloneLabels = { frag_95041c54da629d99: "Hero — Top Providers. Bottom line results." };

test("Layers list the header, the page's sections in order, then the footer", () => {
  assert.deepEqual(
    siteLayerRows({ cloneLabels, route: "/", selection: null, site }).map((row) => [row.label, row.target, row.componentId, row.icon]),
    [
      ["Header", "shell", "header", "div"],
      ["Hero — Top Providers. Bottom line results.", "/", "hero", "layout-template"],
      ["Stats band", "/", "proof", "layout-template"],
      ["Analysis steps", "/", "steps", "layout-template"],
      ["Footer", "shell", "footer", "div"],
    ],
  );
});

test("the selected row is active; a site without a shell has no header or footer rows", () => {
  const rows = siteLayerRows({ cloneLabels, route: "/", selection: { componentId: "proof", target: "/" }, site });
  assert.deepEqual(rows.filter((row) => row.active).map((row) => row.componentId), ["proof"]);
  const header = siteLayerRows({ cloneLabels, route: "/", selection: { componentId: "header", target: "shell" }, site });
  assert.deepEqual(header.filter((row) => row.active).map((row) => row.key), ["shell#header"]);
  assert.equal(siteLayerRows({ cloneLabels, route: "/", selection: null, site: { ...site, shell: null } }).length, 3);
  assert.deepEqual(siteLayerRows({ cloneLabels, route: "/gone", selection: null, site }), []);
});

test("a section the brand no longer knows is just a Section — the marketer never sees 'clone'", () => {
  assert.equal(componentLabel("ClonedSection", { fragmentId: "frag_gone" }, cloneLabels), "Section");
  assert.equal(componentLabel("CtaBand", { id: "cta" }, cloneLabels), "Call to action band");
});

test("clone labels come from the brand", () => {
  const brand = { clones: { frag_x: { id: "frag_x", label: "Hero — X" } } } as unknown as BrandData;
  assert.deepEqual(cloneLabelsOf(brand), { frag_x: "Hero — X" });
  assert.deepEqual(cloneLabelsOf(null), {});
});

test("the selected section's text elements are listed under it, the selected one active", () => {
  const rows = siteLayerRows({
    cloneLabels,
    route: "/",
    selection: { componentId: "proof", target: "/", elementKey: "stats.0.value", elements: [{ key: "heading", kind: "text", label: "7.4%" }, { key: "stats.0.value", kind: "text", label: "1" }] },
    site,
  });
  assert.deepEqual(
    rows.map((row) => [row.label, row.depth ?? 0, row.elementKey ?? null, row.active]),
    [
      ["Header", 0, null, false],
      ["Hero — Top Providers. Bottom line results.", 0, null, false],
      ["Stats band", 0, null, false],
      ["7.4%", 1, "heading", false],
      ["1", 1, "stats.0.value", true],
      ["Analysis steps", 0, null, false],
      ["Footer", 0, null, false],
    ],
  );
  assert.equal(rows[4].icon, "type");
});

test("with no element selected the section row is active and its elements still show", () => {
  const rows = siteLayerRows({
    cloneLabels, route: "/", site,
    selection: { componentId: "proof", target: "/", elementKey: null, elements: [{ key: "heading", kind: "text", label: "7.4%" }] },
  });
  assert.deepEqual(rows.filter((row) => row.active).map((row) => row.label), ["Stats band"]);
  assert.equal(rows.filter((row) => row.depth === 1).length, 1);
});

// Founder 2026-10-19: the selected section's own outermost box is listed first under it as its
// Background; the row selects that key, and is the active row while the background is selected.
test("the selected section lists its Background first, a box row active while the background is selected", () => {
  const elements = [{ key: "heading", kind: "text" as const, label: "7.4%" }];
  const whole = siteLayerRows({ cloneLabels, route: "/", site, selection: { componentId: "proof", target: "/", elementKey: null, backgroundKey: "root", elements } });
  assert.deepEqual(
    whole.slice(2, 5).map((row) => [row.label, row.depth ?? 0, row.elementKey ?? null, row.active, row.icon]),
    [
      ["Stats band", 0, null, true, "layout-template"],
      ["Background", 1, "root", false, "div"],
      ["7.4%", 1, "heading", false, "type"],
    ],
  );
  const background = siteLayerRows({ cloneLabels, route: "/", site, selection: { componentId: "proof", target: "/", elementKey: "root", backgroundKey: "root", elements } });
  assert.deepEqual(background.filter((row) => row.active).map((row) => row.label), ["Background"]);
  const header = siteLayerRows({ cloneLabels, route: "/", site, selection: { componentId: "header", target: "shell", elementKey: null, backgroundKey: "0", elements: [] } });
  assert.deepEqual(header.slice(0, 2).map((row) => [row.label, row.elementKey ?? null, row.key]), [["Header", null, "shell#header"], ["Background", "0", "shell#header~0"]]);
  const none = siteLayerRows({ cloneLabels, route: "/", site, selection: { componentId: "steps", target: "/", elementKey: null, backgroundKey: null, elements: [] } });
  assert.equal(none.some((row) => row.label === "Background"), false, "a section with no one outermost box has none");
});

test("a button is listed with its section's elements, drawn as a box (plan 3)", () => {
  const rows = siteLayerRows({
    cloneLabels, route: "/", site,
    selection: { componentId: "proof", target: "/", elementKey: "button", elements: [{ key: "heading", kind: "text", label: "7.4%" }, { key: "button", kind: "button", label: "Request the analysis" }] },
  });
  const button = rows.find((row) => row.elementKey === "button");
  assert.deepEqual([button?.icon, button?.active, button?.depth], ["rectangle", true, 1]);
});

// Plan 4: Layers is the selected section's tree: boxes, texts, buttons and images nested by parent,
// boxes by their names, hidden header and footer parts marked.
test("Layers nests boxes, texts and images by parent, names boxes and marks hidden parts", () => {
  const elements = [
    { key: "stats", kind: "container" as const, label: "Grid", parent: null },
    { key: "stats.0", kind: "container" as const, label: "Card", parent: "stats" },
    { key: "stats.0.value", kind: "text" as const, label: "7%", parent: "stats.0" },
    { key: "image", kind: "image" as const, label: "Image", parent: null },
    { key: "source", kind: "text" as const, label: "Source", parent: null },
  ];
  const rows = siteLayerRows({ cloneLabels, route: "/", selection: { componentId: "proof", target: "/", elementKey: "stats.0", elements }, site });
  assert.deepEqual(
    rows.filter((row) => row.elementKey).map((row) => [row.label, row.depth, row.icon, row.active]),
    [
      ["Grid", 1, "div", false],
      ["Card", 2, "div", true],
      ["7%", 3, "type", false],
      ["Image", 1, "image", false],
      ["Source", 1, "type", false],
    ],
  );
  const header = siteLayerRows({
    cloneLabels, route: "/", site,
    selection: { componentId: "header", target: "shell", elementKey: null, elements: [{ key: "logo", kind: "image", label: "Logo", parent: "brand", hidden: true }, { key: "brand", kind: "container", label: "Row", parent: null }] },
  });
  assert.ok(header.some((row) => row.label === "Logo (hidden)" && row.depth === 2), JSON.stringify(header));
});

// Founder 2026-10-19: Layers runs to the bottom of the panel (or to the chat box's top when it is open),
// never a fixed half; when the parts above leave too little room it keeps a usable height and the
// panel scrolls.
test("Layers takes the room left down to the bottom of the dock", () => {
  assert.equal(layerListHeight({ dockHeight: 1000, listTop: 300 }), 1000 - 300 - 16);
  assert.equal(layerListHeight({ dockHeight: 600, listTop: 500 }), 240, "too little room: the minimum, the panel scrolls");
  assert.equal(layerListHeight({ dockHeight: 0, listTop: 0 }), 240);
  // The section's real padding and border below the list, so the panel does not overflow by a hairline.
  assert.equal(layerListHeight({ dockHeight: 1096, listTop: 98, bottomGap: 16.5 }), 1096 - 98 - 17);
});
