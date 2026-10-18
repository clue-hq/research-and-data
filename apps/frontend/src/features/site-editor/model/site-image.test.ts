// Site element inspector, plan 5: an image's alt text and where Replace writes its file (rulings R1, R2).
import assert from "node:assert/strict";
import { test } from "node:test";
import type { Clone } from "@clue/site-kit";
import { componentProps } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { ALT_REFUSED, commitImageAlt, imageAltOf, imageReplaceTarget } from "./site-image";

const clone: Clone = {
  id: "frag_0000000000000000", role: "section", label: "T", page_url: "https://seller.example/", section_index: 0, wrapper_class: "w", css: "",
  html: '<div><img data-lumen-slot="hero" src="/brands/a.jpg" alt="Captured"></div>', slots: { hero: { kind: "image", fallback: "/brands/a.jpg" } },
};
const brand = { clones: { [clone.id]: clone } } as never;
const site = () =>
  ({
    id: "doc", title: "A", theme: {}, agent_sections: {},
    shell: {
      header: { type: "SiteHeader", props: { id: "header", accountLine: "C", accountLogo: "/brands/c.png", ctaLabel: "Go", ctaHref: "/" } },
      footer: { type: "SiteFooter", props: { id: "footer", legal: "©", privacyHref: "", termsHref: "" } },
    },
    pages: { "/": { root: { props: { title: "Home" } }, content: [
      { type: "FeatureSplit", props: { id: "f", heading: "H", body: "B", image: "/brands/x.png" } },
      { type: "ClonedSection", props: { id: "c", fragmentId: clone.id, slots: {}, replacements: [], links: [] } },
    ] } },
  }) as unknown as SiteDocument;
const feature = { componentId: "f", target: "/", element: { key: "image", altSource: { kind: "prop", prop: "imageAlt" }, image: { alt: "" }, imageSource: { kind: "prop", prop: "image", uses: 1 } } as never };
const copied = { componentId: "c", target: "/", element: { key: "0.0", altSource: { kind: "clone", key: "0.0" }, image: { alt: "Captured" }, imageSource: { kind: "slot", slot: "hero", uses: 2 } } as never };

test("alt text is written to its prop, a clone's alts, or refused", () => {
  const prop = commitImageAlt(site(), feature, '  Dr. "Smith" & <team>  ', brand);
  assert.ok(prop && "site" in prop);
  assert.equal(componentProps(prop.site, "/", "f")!.imageAlt, 'Dr. "Smith" & <team>');
  const cloned = commitImageAlt(site(), copied, "Hotel lobby", brand);
  assert.ok(cloned && "site" in cloned);
  assert.deepEqual(componentProps(cloned.site, "/", "c")!.alts, { "0.0": "Hotel lobby" });
  assert.deepEqual(commitImageAlt(site(), feature, "x".repeat(301), brand), { refused: ALT_REFUSED });
  assert.deepEqual(commitImageAlt(site(), feature, "a\u0007b", brand), { refused: ALT_REFUSED });
  assert.equal(ALT_REFUSED, "Alt text is plain text of at most 300 characters, with no line breaks.");
  const header = { componentId: "header", target: "shell", element: { key: "accountLogo", altSource: { kind: "prop", prop: "accountLogoAlt" }, image: { alt: "" } } as never };
  const shell = commitImageAlt(site(), header, "Carmel Clay", brand);
  assert.ok(shell && "site" in shell);
  assert.equal(componentProps(shell.site, "shell", "header")!.accountLogoAlt, "Carmel Clay");
});

test("an empty alt removes the prop; an alt back to the captured one drops the clone entry; no change is no save", () => {
  const set = commitImageAlt(site(), feature, "Room", brand) as { site: SiteDocument };
  const cleared = commitImageAlt(set.site, feature, "  ", brand) as { site: SiteDocument };
  assert.equal("imageAlt" in componentProps(cleared.site, "/", "f")!, false);
  const once = commitImageAlt(site(), copied, "Lobby", brand) as { site: SiteDocument };
  const back = commitImageAlt(once.site, copied, "Captured", brand) as { site: SiteDocument };
  assert.equal("alts" in componentProps(back.site, "/", "c")!, false);
  assert.equal(commitImageAlt(once.site, copied, "Lobby", brand), null);
  const fixed = { ...feature, element: { ...(feature.element as object), altSource: { kind: "fixed", reason: "ask" } } as never };
  assert.equal(commitImageAlt(site(), fixed, "x", brand), null);
});

test("the stored alt is read from its source; a clone with no entry shows its captured alt", () => {
  assert.equal(imageAltOf(site(), feature, brand), "");
  assert.equal(imageAltOf(site(), copied, brand), "Captured");
  const once = commitImageAlt(site(), copied, "Lobby", brand) as { site: SiteDocument };
  assert.equal(imageAltOf(once.site, copied, brand), "Lobby");
  assert.equal(imageAltOf(site(), { ...feature, element: { ...(feature.element as object), altSource: { kind: "fixed", reason: "ask" } } as never }, brand), null);
});

test("Replace targets the image prop, the header's account logo, a clone slot and an agent's named prop; none when fixed", () => {
  assert.deepEqual(imageReplaceTarget(feature), { prop: "image", uses: 1 });
  assert.deepEqual(imageReplaceTarget(copied), { prop: "slots.hero", uses: 2 });
  assert.deepEqual(imageReplaceTarget({ ...feature, element: { ...(feature.element as object), imageSource: { kind: "prop", prop: "photo", uses: 1 } } as never }), { prop: "photo", uses: 1 });
  assert.equal(imageReplaceTarget({ ...feature, element: { ...(feature.element as object), imageSource: { kind: "fixed", reason: "brand kit" } } as never }), null);
});

// Plan 6 (ruling R11): the seller's logo in the header is replaced through its `logo` prop.
test("the header's logo replaces through its prop", () => {
  const logo = { componentId: "header", target: "shell", element: { key: "logo", altSource: { kind: "prop", prop: "logoAlt" }, image: { alt: "" }, imageSource: { kind: "prop", prop: "logo", uses: 1 } } as never };
  assert.deepEqual(imageReplaceTarget(logo), { prop: "logo", uses: 1 });
  const written = commitImageAlt(site(), logo, "Garner Health", brand)!;
  assert.ok(!("refused" in written));
  assert.equal(("site" in written ? written.site : null)!.shell!.header.props.logoAlt, "Garner Health");
});
