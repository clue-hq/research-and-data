// Plan 5 (rulings R1, R2, R5): where an image's file and its alt text are written, by element kind.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { Clone } from "../src/clone";
import { AGENT_ALT, AGENT_IMAGE, CLONE_IMAGE, ICON_NOTE, VIDEO_ALT, VIDEO_REPLACE, imageSourcesOf } from "../src/image-sources";

const clone: Clone = {
  id: "frag_0000000000000000", role: "section", label: "T", page_url: "https://seller.example/", section_index: 0, wrapper_class: "w", css: "",
  html: '<div><img data-lumen-slot="hero" src="/brands/a.jpg"><img data-lumen-slot="hero" src="/brands/a.jpg"><img src="/brands/b.jpg"></div>',
  slots: { hero: { kind: "image", fallback: "/brands/a.jpg" } },
};
const of = (type: string, key: string, props: Record<string, unknown> = {}, media: "img" | "video" | "svg" = "img", c: Clone | null = null, src = "/brands/x.png") =>
  imageSourcesOf({ clone: c, key, media, props, src, type });

test("our image, the header's account logo and the seller's logo", () => {
  assert.deepEqual(of("FeatureSplit", "image"), { alt: { kind: "prop", prop: "imageAlt" }, image: { kind: "prop", prop: "image", uses: 1 } });
  assert.deepEqual(of("SiteHeader", "accountLogo"), { alt: { kind: "prop", prop: "accountLogoAlt" }, image: { kind: "prop", prop: "accountLogo", uses: 1 } });
  // Plan 6 (ruling R11): the seller's logo in the header and footer is replaced through its prop.
  assert.deepEqual(of("SiteHeader", "logo"), { alt: { kind: "prop", prop: "logoAlt" }, image: { kind: "prop", prop: "logo", uses: 1 } });
  assert.deepEqual(of("SiteFooter", "logo"), { alt: { kind: "prop", prop: "logoAlt" }, image: { kind: "prop", prop: "logo", uses: 1 } });
});

test("a copied image through its slot (with how many images it fills), else fixed; its alt by key", () => {
  assert.deepEqual(of("ClonedSection", "0.0", {}, "img", clone), { alt: { kind: "clone", key: "0.0" }, image: { kind: "slot", slot: "hero", uses: 2 } });
  assert.deepEqual(of("ClonedSection", "0.2", {}, "img", clone), { alt: { kind: "clone", key: "0.2" }, image: { kind: "fixed", reason: CLONE_IMAGE } });
  assert.equal(CLONE_IMAGE, "This image is copied from the seller's page and has no slot; ask the agent to change it.");
});

test("an agent's image named after the prop holding it; otherwise the agent's", () => {
  assert.deepEqual(of("QuoteBand", "photo", { photo: "/brands/x.png" }).image, { kind: "prop", prop: "photo", uses: 1 });
  assert.deepEqual(of("QuoteBand", "hero", { photo: "/brands/x.png" }).image, { kind: "fixed", reason: AGENT_IMAGE });
  assert.deepEqual(of("QuoteBand", "photo", { photo: "/brands/x.png" }).alt, { kind: "fixed", reason: AGENT_ALT });
  assert.equal(AGENT_IMAGE, "The agent's section sets this image; ask the agent to change it.");
  assert.equal(AGENT_ALT, "The agent's section sets this image's alt text; ask the agent to change it.");
});

test("videos and icons", () => {
  assert.deepEqual(of("ClonedSection", "0.0", {}, "video", clone), { alt: { kind: "fixed", reason: VIDEO_ALT }, image: { kind: "fixed", reason: VIDEO_REPLACE } });
  assert.deepEqual(of("ClonedSection", "0.0", {}, "svg", clone), { alt: { kind: "fixed", reason: ICON_NOTE }, image: { kind: "fixed", reason: ICON_NOTE } });
  assert.equal(VIDEO_REPLACE, "Ask the agent to change a video.");
  assert.equal(VIDEO_ALT, "Videos have no alt text; the agent can describe one in the words beside it.");
  assert.equal(ICON_NOTE, "This is an icon drawn in code; ask the agent to change it.");
});

test("review I3: an agent's named prop is the image's source only when it holds the file the image draws", () => {
  assert.deepEqual(of("QuoteBand", "photo", { photo: "/brands/x.png", hero: "/brands/y.png" }, "img", null, "/brands/x.png").image, { kind: "prop", prop: "photo", uses: 1 });
  assert.deepEqual(of("QuoteBand", "photo", { photo: "/brands/x.png", hero: "/brands/y.png" }, "img", null, "/brands/y.png").image, { kind: "fixed", reason: AGENT_IMAGE });
});
