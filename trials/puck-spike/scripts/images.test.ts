// R3 (founder-approved 2026-10-09): a page may use the brand's images and the images generated for
// its own site; another site's generated image is refused; the header's account logo must be this
// site's account logo file.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import { validate } from "./validate-page";

const SPIKE = path.join(__dirname, "..");
const site = JSON.parse(fs.readFileSync(path.join(SPIKE, "data", "sites", "garner-syracuse.json"), "utf-8"));
const SITE = `images-test-${process.pid}`;
const GENERATED = `/generated/${SITE}/abc123.png`;
fs.mkdirSync(path.join(SPIKE, "public", "generated", SITE), { recursive: true });
fs.writeFileSync(path.join(SPIKE, "public", GENERATED), "png");
after(() => fs.rmSync(path.join(SPIKE, "public", "generated", SITE), { recursive: true, force: true }));

function withImage(image: string, accountLogo = ""): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "images-"));
  const page = structuredClone(site.pages["/"]);
  const split = { type: "FeatureSplit", props: { id: "img", surface: "page", heading: "A heading", body: "Some words.", image } };
  page.content.push(split);
  fs.writeFileSync(path.join(dir, ".run.json"), JSON.stringify({ brand: "garner", site: SITE, route: "/" }));
  fs.writeFileSync(path.join(dir, "page.json"), JSON.stringify(page));
  fs.mkdirSync(path.join(dir, "pages"));
  fs.writeFileSync(path.join(dir, "pages", "analysis.json"), JSON.stringify(site.pages["/analysis"]));
  fs.writeFileSync(path.join(dir, "shell.json"), JSON.stringify({ ...site.shell, header: { ...site.shell.header, accountLogo } }));
  return dir;
}

test("an image generated for this site is accepted", () => {
  const result = validate(withImage(GENERATED));
  assert.equal(result.valid, true, result.errors.join("\n"));
});

test("another site's generated image, or a missing one, is refused", () => {
  for (const image of ["/generated/other-site/abc123.png", `/generated/${SITE}/missing.png`]) {
    const result = validate(withImage(image));
    assert.equal(result.valid, false);
    assert.ok(result.errors.some((e) => e.includes(image) && e.includes("generated for this site")), result.errors.join("\n"));
  }
});

test("the account logo must be this site's account logo file", () => {
  const result = validate(withImage(GENERATED, "/accounts/other-site/light_lockup.svg"));
  assert.equal(result.valid, false);
  assert.ok(result.errors.some((e) => e.startsWith("shell.header.accountLogo")), result.errors.join("\n"));
});
