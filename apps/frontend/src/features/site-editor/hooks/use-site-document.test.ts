// The editor keeps a site's brand for the visit and reads it again when a load shows a cloned
// section it lacks. Since the design API sends only the sections the site places (site loading,
// 2026-10-29), that check must cover the header and footer too, not only the pages.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "@clue/site-kit";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { brandHasClonesOf } from "./use-site-document";

const HERO = "frag_00000000000000a1";
const HEADER = "frag_00000000000000b2";
const brandWith = (...ids: string[]) =>
  ({ clones: Object.fromEntries(ids.map((id) => [id, { id }])) }) as unknown as BrandData;
const site = (shellHeader: Record<string, unknown> | null) =>
  ({
    pages: { "/": { root: { props: {} }, content: [{ type: "ClonedSection", props: { id: "hero", fragmentId: HERO } }] } },
    shell: shellHeader && { header: shellHeader, footer: { type: "SiteFooter", props: { id: "footer" } } },
  }) as unknown as SiteDocument;

test("a page's cloned section the brand lacks needs the brand read again", () => {
  assert.equal(brandHasClonesOf(brandWith(), site(null)), false);
  assert.equal(brandHasClonesOf(brandWith(HERO), site(null)), true);
});

test("a header the agent made from a cloned section needs the brand read again too", () => {
  const header = { type: "ClonedSection", props: { id: "header", fragmentId: HEADER } };
  assert.equal(brandHasClonesOf(brandWith(HERO), site(header)), false);
  assert.equal(brandHasClonesOf(brandWith(HERO, HEADER), site(header)), true);
  assert.equal(brandHasClonesOf(brandWith(HERO), site({ type: "SiteHeader", props: { id: "header" } })), true);
});
