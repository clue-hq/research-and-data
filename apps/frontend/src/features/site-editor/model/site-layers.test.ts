import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "@clue/site-kit";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import { cloneLabelsOf, componentLabel, siteLayerRows } from "./site-layers";

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
  shell: { header: { id: "header" }, footer: { id: "footer" } },
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
