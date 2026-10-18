// Site element inspector, plan 6 (rulings R10, R12): the header's own placement — sticky and
// see-through over the first section — as pure decisions over the app's copy of the site.
import assert from "node:assert/strict";
import { test } from "node:test";
import { componentProps } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { commitHeaderPlacement, headerPlacementState } from "./site-shell";

const site = {
  id: "doc", title: "A", theme: {}, agent_sections: {},
  pages: { "/": { root: { props: { title: "Home" } }, content: [] } },
  shell: {
    header: { type: "SiteHeader", props: { id: "header", accountLine: "For C", ctaLabel: "Go", ctaHref: "/", _edits: { logo: { borderWidth: 1 } } } },
    footer: { type: "SiteFooter", props: { id: "footer", legal: "©" } },
  },
} as unknown as SiteDocument;

test("only the header itself has a placement", () => {
  assert.deepEqual(headerPlacementState(site, { target: "shell", componentId: "header", element: null }), { sticky: false, overlay: false });
  assert.equal(headerPlacementState(site, { target: "shell", componentId: "footer", element: null }), null);
  assert.equal(headerPlacementState(site, { target: "shell", componentId: "header", element: { key: "logo" } }), null);
  assert.equal(headerPlacementState(site, { target: "/", componentId: "hero", element: null }), null);
  assert.equal(headerPlacementState(null, { target: "shell", componentId: "header", element: null }), null);
});

test("sticky and overlay are written on the header's root and removed exactly", () => {
  const sticky = commitHeaderPlacement(site, "sticky", true)!;
  assert.deepEqual(componentProps(sticky.site, "shell", "header")!._edits, { logo: { borderWidth: 1 }, root: { sticky: true } });
  assert.deepEqual(headerPlacementState(sticky.site, { target: "shell", componentId: "header", element: null }), { sticky: true, overlay: false });
  const both = commitHeaderPlacement(sticky.site, "overlay", true)!;
  assert.deepEqual((componentProps(both.site, "shell", "header")!._edits as Record<string, unknown>).root, { sticky: true, overlay: true });
  const off = commitHeaderPlacement(commitHeaderPlacement(both.site, "overlay", false)!.site, "sticky", false)!;
  assert.deepEqual(componentProps(off.site, "shell", "header"), componentProps(site, "shell", "header"));
  assert.equal(commitHeaderPlacement(site, "sticky", false), null, "nothing changes");
});
