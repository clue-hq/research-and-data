import assert from "node:assert/strict";
import { pageMenuLink } from "@clue/site-kit";
import { test } from "node:test";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import { linkPatch, linkRowState, sitePages } from "./site-link-row.logic";

const TYPO = { color: "#014036", fontFamily: "Garner Serif", fontSize: 18, fontWeight: 400, italic: false, underline: false, textAlign: "left" as const };
const site = SiteDocumentSchema.parse({
  id: "doc-a",
  title: "A",
  theme: {},
  pages: {
    "/": {
      root: { props: { title: "Home" } },
      content: [
        { type: "ProofCard", props: { id: "proof", heading: "See the analysis now", body: 'Read <a href="/analysis">the study</a> today', linkLabel: "Read", linkHref: "/" } },
        { type: "ClonedSection", props: { id: "hero", fragmentId: "frag_0000000000000001", slots: {}, replacements: [], links: [] } },
      ],
    },
    "/analysis": { root: { props: { title: "The analysis" } }, content: [] },
  },
  shell: {
    header: { type: "SiteHeader", props: { id: "header", accountLine: "SCSD", ctaLabel: "Go", ctaHref: "/", menuExtra: [{ label: "Pricing", href: "https://seller.example/pricing" }] } },
    footer: { type: "SiteFooter", props: { id: "footer", legal: "©" } },
  },
  agent_sections: {},
});
type Sel = NonNullable<Parameters<typeof linkRowState>[1]>;
const el = (over: object) => ({ key: "heading", kind: "text" as const, label: "x", computed: TYPO, rich: null, words: null, link: null, ...over });
const words = (start: number, end: number, text: string) => ({ start, end, count: 1, text, computed: TYPO });
const sel = (componentId: string, element: object, target = "/", componentType = "ProofCard"): Sel => ({ componentId, componentType, target, element: el(element) });

test("the pages a link may go to are the site's own, by title", () => {
  assert.deepEqual(sitePages(site), [{ route: "/", title: "Home" }, { route: "/analysis", title: "The analysis" }]);
});

test("an own link shows its address and new tab from the app's copy, and is changed there", () => {
  const selection = sel("proof", { key: "linkLabel", link: { source: { kind: "prop", href: "linkHref", newTab: "linkNewTab" } } });
  assert.deepEqual(linkRowState(site, selection), { kind: "link", href: "/", newTab: false, removable: false, shared: false });
  const edit = linkPatch(site, selection, { href: "/analysis", newTab: true });
  assert.ok(edit && "props" in edit);
  assert.equal(edit.props.linkHref, "/analysis");
  assert.equal(edit.props.linkNewTab, true);
});

test("words in rich text: no link yet offers to make one; a link in them is edited whole; removing unwraps it", () => {
  const plain = sel("proof", { rich: { prop: "heading" }, words: words(4, 16, "the analysis") });
  assert.deepEqual(linkRowState(site, plain), { kind: "link", href: "", newTab: false, removable: false, shared: false });
  const made = linkPatch(site, plain, { href: "/analysis", newTab: false });
  assert.ok(made && "props" in made);
  assert.equal(made.props.heading, 'See <a href="/analysis">the analysis</a> now');
  const inLink = sel("proof", { key: "body", rich: { prop: "body" }, words: words(9, 12, "stu") });
  assert.deepEqual(linkRowState(site, inLink), { kind: "link", href: "/analysis", newTab: false, removable: true, shared: false });
  const removed = linkPatch(site, inLink, null);
  assert.ok(removed && "props" in removed);
  assert.equal(removed.props.body, "Read the study today");
});

test("a whole rich text box with nothing highlighted becomes a link as a whole", () => {
  const box = sel("proof", { rich: { prop: "heading" } });
  const edit = linkPatch(site, box, { href: "#top", newTab: false });
  assert.ok(edit && "props" in edit);
  assert.equal(edit.props.heading, '<a href="#top">See the analysis now</a>');
});

test("a clone link is written through its slot, or else a link replacement; new tab by its element key", () => {
  const slot = sel("hero", { key: "0.2", link: { source: { kind: "slot", slot: "cta" }, href: "/start" } }, "/", "ClonedSection");
  assert.deepEqual(linkRowState(site, slot), { kind: "link", href: "/start", newTab: false, removable: false, shared: false });
  const viaSlot = linkPatch(site, slot, { href: "/analysis", newTab: true });
  assert.ok(viaSlot && "props" in viaSlot);
  assert.deepEqual([viaSlot.props.slots, viaSlot.props.newTab], [{ cta: "/analysis" }, ["0.2"]]);
  const replaced = sel("hero", { key: "0.0", link: { source: { kind: "replacement", find: "/demo", shared: true }, href: "https://seller.example/demo" } }, "/", "ClonedSection");
  assert.deepEqual(linkRowState(site, replaced), { kind: "link", href: "https://seller.example/demo", newTab: false, removable: false, shared: true });
  const viaReplacement = linkPatch(site, replaced, { href: "/analysis", newTab: false });
  assert.ok(viaReplacement && "props" in viaReplacement);
  assert.deepEqual(viaReplacement.props.links, [{ find: "/demo", replace: "/analysis" }]);
  const again = linkPatch(viaReplacement.site, replaced, { href: "https://x.com", newTab: false });
  assert.ok(again && "props" in again);
  assert.deepEqual(again.props.links, [{ find: "/demo", replace: "https://x.com" }], "the same replacement is changed, never added twice");
});

test("an address that is not one, or a page the site does not have, is refused with a note", () => {
  const selection = sel("proof", { key: "linkLabel", link: { source: { kind: "prop", href: "linkHref", newTab: "linkNewTab" } } });
  assert.deepEqual(linkPatch(site, selection, { href: "javascript:alert(1)", newTab: false }), { refused: "Use a page of this site (like /analysis), a web address starting with https://, a #section or a mailto: address." });
  assert.deepEqual(linkPatch(site, selection, { href: "/missing", newTab: false }), { refused: "This site has no page /missing. Its pages are /, /analysis." });
  assert.deepEqual(linkPatch(site, selection, { href: "example.com", newTab: false }), { refused: "Use a page of this site (like /analysis), a web address starting with https://, a #section or a mailto: address." });
});

test("where no link can be made the row says why", () => {
  assert.deepEqual(linkRowState(site, sel("hero", { key: "0.1" }, "/", "ClonedSection")), {
    kind: "none",
    reason: "This text is copied from the seller's page and has no slot, so it cannot become a link.",
  });
  // Plan 6 (ruling R11): the header's text is like any section's; a page menu item says why.
  assert.deepEqual(linkRowState(site, sel("header", { key: "divider" }, "shell", "SiteHeader")), { kind: "none", reason: "This text cannot become a link." });
  assert.deepEqual(linkRowState(site, sel("header", { key: "menu.analysis", link: { source: { kind: "fixed", reason: pageMenuLink("Analysis") } } }, "shell", "SiteHeader")), {
    kind: "none",
    reason: "This link opens the site's Analysis page; the menu follows the site's pages.",
  });
  assert.deepEqual(linkRowState(site, sel("proof", { key: "cta", link: { source: { kind: "fixed", reason: "The agent's section sets this link; ask the agent to change it." } } }, "/", "Probe")), {
    kind: "none",
    reason: "The agent's section sets this link; ask the agent to change it.",
  });
});

// End-of-plan review findings 1 and 2.
test("words whose text no longer matches are refused, never linked in the wrong place", () => {
  const stale = sel("proof", { rich: { prop: "heading" }, words: words(4, 16, "something el") });
  assert.deepEqual(linkPatch(site, stale, { href: "/analysis", newTab: false }), { refused: "The text changed. Highlight the words again." });
  assert.deepEqual(linkRowState(site, stale), { kind: "none", reason: "The text changed. Highlight the words again." });
});

test("words highlighted in text that is already a link change that link, never nest another inside it", () => {
  const slot = sel("hero", { key: "0.2", rich: { prop: "slots.cta_label", fallback: "Start now" }, words: words(0, 5, "Start"), link: { source: { kind: "slot", slot: "cta" }, href: "/start" } }, "/", "ClonedSection");
  assert.deepEqual(linkRowState(site, slot), { kind: "link", href: "/start", newTab: false, removable: false, shared: false });
  const edit = linkPatch(site, slot, { href: "/analysis", newTab: false });
  assert.ok(edit && "props" in edit);
  assert.deepEqual(edit.props.slots, { cta: "/analysis" }, "the outer link is changed; the words stay unlinked");
  const agent = sel("proof", { key: "cta", rich: { prop: "cta" }, words: words(0, 3, "Rea"), link: { source: { kind: "fixed", reason: "The agent's section sets this link; ask the agent to change it." } } }, "/", "Probe");
  assert.deepEqual(linkRowState(site, agent), { kind: "none", reason: "The agent's section sets this link; ask the agent to change it." });
  assert.equal(linkPatch(site, agent, { href: "/analysis", newTab: false }), null);
});

test("the Link row and the save check share one address rule", () => {
  const selection = sel("proof", { key: "linkLabel", link: { source: { kind: "prop", href: "linkHref", newTab: "linkNewTab" } } });
  assert.deepEqual(linkPatch(site, selection, { href: "//evil.example", newTab: false }), { refused: "Use a page of this site (like /analysis), a web address starting with https://, a #section or a mailto: address." });
});

test("a copied button's new tab counts a key on its words too, and Same tab clears both (review 3)", () => {
  const withWordsKey = linkPatch(site, sel("hero", { key: "0.2.1", link: { source: { kind: "slot", slot: "cta" }, href: "/start" } }, "/", "ClonedSection"), { href: "/analysis", newTab: true });
  assert.ok(withWordsKey && "props" in withWordsKey);
  assert.deepEqual(withWordsKey.props.newTab, ["0.2.1"], "set while the words were selected as text");
  const button = sel("hero", { key: "0.2", kind: "button", link: { source: { kind: "slot", slot: "cta" }, href: "/start" } }, "/", "ClonedSection");
  assert.deepEqual(linkRowState(withWordsKey.site, button), { kind: "link", href: "/analysis", newTab: true, removable: false, shared: false }, "the button shows New tab");
  const same = linkPatch(withWordsKey.site, button, { href: "/analysis", newTab: false });
  assert.ok(same && "props" in same);
  assert.equal(same.props.newTab, undefined, "Same tab removes the words' key as well");
});

// Plan 6 (ruling R8): an extra menu link is edited where it lives, in menuExtra.
test("an extra menu link edits menuExtra", () => {
  const extra = sel("header", { key: "menu._0", link: { source: { kind: "prop", href: "menuExtra.0.href", newTab: "menuExtra.0.newTab" }, href: "https://seller.example/pricing" } }, "shell", "SiteHeader");
  assert.deepEqual(linkRowState(site, extra), { href: "https://seller.example/pricing", kind: "link", newTab: false, removable: false, shared: false });
  const patched = linkPatch(site, extra, { href: "https://seller.example/plans", newTab: true });
  assert.ok(patched && "props" in patched);
  assert.deepEqual((patched as unknown as { props: { menuExtra: unknown } }).props.menuExtra, [{ label: "Pricing", href: "https://seller.example/plans", newTab: true }]);
});
