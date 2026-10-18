// Site element inspector, plan 6 (rulings R10, R12): the header's own placement — sticky and
// see-through over the first section — as pure decisions over the app's copy of the site.
import assert from "node:assert/strict";
import { test } from "node:test";
import { componentProps } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { accountShownState, commitAccountShown, commitHeaderPlacement, headerPlacementState } from "./site-shell";

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

// The account logo's own Visibility is the template's "Account shown" (the logo and the thin line
// before it hide together).
const templated = {
  ...site,
  shell: { ...site.shell, header: { type: "ClonedSection", props: { id: "header", fragmentId: "frag_1", slots: { account_line: "Prepared for C" }, replacements: [], links: [] } } },
} as unknown as SiteDocument;
const accountLogo = { target: "shell", componentId: "header", element: { key: "0.0.1.1", imageSource: { kind: "slot", slot: "account_logo", uses: 1 } } };

test("hiding the account logo turns the template's account_shown off, and showing removes it", () => {
  assert.deepEqual(accountShownState(templated, accountLogo), { hidden: false, part: "header" });
  const hidden = commitAccountShown(templated, accountLogo, true)!;
  assert.equal((componentProps(hidden.site, "shell", "header")!.slots as Record<string, unknown>).account_shown, false);
  assert.deepEqual(accountShownState(hidden.site, accountLogo), { hidden: true, part: "header" });
  const shown = commitAccountShown(hidden.site, accountLogo, false)!;
  assert.deepEqual(componentProps(shown.site, "shell", "header"), componentProps(templated, "shell", "header"));
  assert.equal(accountShownState(templated, { ...accountLogo, element: { key: "0.0.0", imageSource: { kind: "slot", slot: "image", uses: 1 } } }), null, "another image is not the account logo");
});
