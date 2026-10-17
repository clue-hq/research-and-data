// Contract 1 (2026-10-11): every image, logo, font and generated picture a site names is
// /asset-store/<sha256>, a blob of the workspace. The spike's /brands, /generated and /accounts
// paths are gone; the validator takes this site's generated images and the account's logos as data.
import assert from "node:assert/strict";
import { test } from "node:test";
import { brandData } from "../src/brand";
import { validateSite } from "../src/validate";
import { garner, site as readSite } from "./fixtures/garner";

const site = readSite("garner-syracuse");
const brand = garner();
const GENERATED = `/asset-store/${"a".repeat(64)}`;
const LOGO = `/asset-store/${"b".repeat(64)}`;
const STORE = /^\/asset-store\/[0-9a-f]{64}$/;

function withImage(image: string) {
  const analysis = structuredClone(site.pages["/analysis"]);
  analysis.content[0].props.image = image; // FeatureSplit "what"
  return { "/": site.pages["/"], "/analysis": analysis };
}

test("every brand asset, font and clone image is an /asset-store/<sha256> path", () => {
  for (const asset of Object.values(brand.assets)) assert.match(asset.file, STORE, asset.file);
  for (const face of brand.fonts) assert.match(face.file, STORE, face.file);
  assert.ok(Object.values(brand.assets).some((asset) => asset.kind === "captured_image"), "clone images are offered");
});

test("an image generated for this site is accepted; an image that is not is refused", () => {
  const files = { pages: withImage(GENERATED), shell: site.shell };
  assert.equal(validateSite(files, brand, {}, { siteImages: [GENERATED], accountLogos: [] }).valid, true);
  const refused = validateSite(files, brand, {});
  assert.ok(
    refused.errors.includes(`pages/analysis.content.0(what).image: image "${GENERATED}" is not in the brand's assets; pick a file from brand/brand.md`),
    refused.errors.join("\n"),
  );
});

test("the spike's old paths are refused", () => {
  for (const legacy of ["/brands/garner/assets/x.png", "/generated/garner-syracuse/x.png", "/accounts/garner-syracuse/logo.png"]) {
    assert.equal(validateSite({ pages: withImage(legacy), shell: site.shell }, brand, {}).valid, false, legacy);
  }
});

test("the header's account logo must be one of the account's logos", () => {
  const shell = structuredClone(site.shell);
  shell.header.accountLogo = LOGO;
  const pages = { "/": site.pages["/"], "/analysis": site.pages["/analysis"] };
  assert.equal(validateSite({ pages, shell }, brand, {}, { siteImages: [], accountLogos: [LOGO] }).valid, true);
  const refused = validateSite({ pages, shell }, brand, {});
  assert.ok(
    refused.errors.includes(`shell.header.accountLogo: "${LOGO}" is not this account's logo; use a file from "The account's logo" in brand/brand.md, or leave it empty`),
    refused.errors.join("\n"),
  );
});

test("an /asset-store image inside an agent section's props is checked like any other", () => {
  const home = structuredClone(site.pages["/"]);
  home.content.push({ type: "QuoteBand", props: { id: "quote", surface: "page", photo: GENERATED } });
  const sections = { QuoteBand: { schema: { safeParse: () => ({ success: true }) } } };
  const result = validateSite({ pages: { "/": home, "/analysis": site.pages["/analysis"] }, shell: site.shell }, brand, sections);
  assert.ok(result.errors.some((e) => e.startsWith(`page.content.5(quote).photo: image "${GENERATED}"`)), result.errors.join("\n"));
});

test("a captured image is described by its digest's stored description first, then its alt, then its section", () => {
  const [d1, d2, d3] = ["1", "2", "3"].map((c) => c.repeat(64));
  const clone = {
    id: "frag_a", role: "hero", label: "Hero", page_url: "", section_index: 0, wrapper_class: "lumen-frag-a", css: "",
    slots: {}, degraded_note: null,
    html: `<img src="/asset-store/${d1}" alt="A team"><img src="/asset-store/${d2}" alt="Doctors"><img src="/asset-store/${d3}">`,
  } as unknown as Parameters<typeof brandData>[0]["clones"][number];
  const described = brandData({ slug: "x", kit: {}, fonts: [], kitAssets: {}, clones: [clone],
    capturedImageDescriptions: { [d1]: "Three nurses laughing at a station." } });
  assert.equal(described.assets[`/asset-store/${d1}`].description, "Three nurses laughing at a station.");
  assert.equal(described.assets[`/asset-store/${d2}`].description, "Doctors");
  assert.equal(described.assets[`/asset-store/${d3}`].description, 'From the seller\'s section "Hero"');
});
