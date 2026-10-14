// The agent kit (Wave 2 A9): logos whole, looks by name, the seller's own icon, links and cards drawn
// like the seller's, and any of the brand's surfaces.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { Config } from "@puckeditor/core";
import type { ReactElement, ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { z } from "zod";
import { makeKit, type Kit } from "../src/agent-kit";
import { makeConfig } from "../src/config";
import { colorOf, styleOf } from "../src/brand-values";
import { buttonLooks, cardLooks } from "../src/looks";
import { logoFiles } from "../src/shell";
import { garner } from "./fixtures/garner";
import { kitBrand } from "./fixtures/kits";

const href = (value: string) => (value.startsWith("/") && !value.startsWith("//") ? `/s/x${value === "/" ? "" : value}` : value);
const html = (node: ReactNode) => renderToStaticMarkup(<>{node}</>);

test("a logo from the kit is shown whole; fit decides for every other image", () => {
  const brand = garner();
  const kit = makeKit(href, brand);
  const logo = [...logoFiles(brand)][0];
  assert.match(html(kit.Image({ src: logo })), /class="h-full w-full object-contain"/);
  const photo = Object.values(brand.assets).find((asset) => asset.kind === "raster_image" && !logoFiles(brand).has(asset.file))!.file;
  assert.match(html(kit.Image({ src: photo })), /class="w-full rounded-card object-cover"/);
  assert.match(html(kit.Image({ src: photo, fit: "contain" })), /class="h-full w-full object-contain"/);
  assert.match(html(kit.Image({ src: photo, fit: "fill" })), /class="absolute inset-0 h-full w-full object-cover"/);
});

test("a button is the standard button or a look by name, with no arrow of site-kit's own", () => {
  const brand = kitBrand("garner.minted");
  const kit = makeKit(href, brand);
  const standard = html(kit.Button({ label: "Request the analysis", href: "/analysis", surface: "page" }));
  assert.ok(standard.includes('href="/s/x/analysis"') && standard.includes('class="brand-btn"'), standard);
  assert.ok(!standard.includes("→"), standard);
  const outline = buttonLooks(brand).find((look) => look.name === "outline.1")!;
  assert.ok(html(kit.Button({ label: "See how", href: "/", surface: "page", look: "outline.1" })).includes(`class="brand-btn brand-look-${outline.index}"`));
  assert.ok(html(kit.Button({ label: "x", href: "/", surface: "page", look: "solid.9" })).includes('class="brand-btn"'), "an unknown look draws the standard button");
  const disabled = html(kit.Button({ label: "Soon", href: "/", surface: "page", disabled: true }));
  assert.ok(disabled.includes('aria-disabled="true"') && !disabled.includes("href="), disabled);
});

test("a look draws the seller's own icon where the site has one", () => {
  const brand = kitBrand("probe.minted");
  const kit = makeKit(href, brand);
  const solid = buttonLooks(brand).find((look) => colorOf(brand, look.measured?.rest.fill) === "#047464")!;
  const markup = html(kit.Button({ label: "Go", href: "/", surface: "page", look: solid.name }));
  assert.match(markup, /<span>Go<\/span><span aria-hidden="true" class="brand-btn-icon"><svg [^>]*viewBox="0 0 12 12"/);
  const outline = buttonLooks(brand).find((look) => look.name === "outline.0d2b25")!;
  assert.ok(html(kit.Button({ label: "More", href: "/", surface: "page", look: outline.name })).includes('<span aria-hidden="true" class="brand-btn-icon">→</span>'));
});

// Review finding S6-2: the seller's CSS often sizes a button's icon (Tailwind's w-4 h-4, Font
// Awesome); its captured markup then has no size and drew at 0x0 on our sites while the Brand page
// showed it. The kit keeps the size the icon was measured at, and the icon is drawn at it.
test("S6-2: a button icon is drawn at the size it was measured at, whatever its markup says", () => {
  const brand = kitBrand("probe.minted");
  const solid = buttonLooks(brand).find((look) => colorOf(brand, look.measured?.rest.fill) === "#047464")!;
  const value = styleOf(brand, solid.measured!.icon!.token) as { kind: "svg"; markup: string; width: number; height: number };
  value.markup = value.markup.replace(/\s(width|height)="[^"]*"/g, "");
  value.width = 16;
  value.height = 14.5;
  const markup = html(makeKit(href, brand).Button({ label: "Go", href: "/", surface: "page", look: solid.name }));
  assert.match(markup, /<span aria-hidden="true" class="brand-btn-icon"><svg width="16" height="14.5" [^>]*viewBox="0 0 12 12"/);
  value.markup = value.markup.replace("<svg", '<svg width="100%" height="1em"');
  const resized = html(makeKit(href, brand).Button({ label: "Go", href: "/", surface: "page", look: solid.name }));
  assert.match(resized, /<svg width="16" height="14.5" /, "the measured size wins over the markup's own");
  assert.equal((resized.match(/ width=/g) ?? []).length, 1);
  delete (value as { width?: number }).width;
  const unmeasured = html(makeKit(href, brand).Button({ label: "Go", href: "/", surface: "page", look: solid.name }));
  assert.ok(unmeasured.includes('<svg width="100%" height="1em"') && !unmeasured.includes("undefined"), "an unmeasured icon is drawn as captured");
});

test("kit.Link and kit.Card are drawn like the seller's links and cards", () => {
  const brand = kitBrand("probe.minted");
  const kit = makeKit(href, brand);
  assert.equal(html(kit.Link({ href: "/analysis", children: "Read" })), '<a href="/s/x/analysis" class="brand-link">Read</a>');
  const card = cardLooks(brand)[0];
  assert.equal(html(kit.Card({ look: card.name, children: "x" })), `<div class="brand-card brand-card-look-${card.index}">x</div>`);
  assert.equal(html(kit.Card({ href: "#proof", children: "x" })), '<a href="#proof" class="brand-card">x</a>');
});

test("a section may stand on any of the brand's surfaces by its choice name", () => {
  const kit = makeKit(href, kitBrand("garner.minted"));
  assert.ok(html(kit.Shell({ surface: "band-014036", children: "x" })).includes('class="bg-surface-band-014036 text-on-surface-band-014036"'));
  assert.ok(html(kit.Shell({ surface: "brandSubtle", children: "x" })).includes('class="bg-surface-brand-subtle text-on-surface-brand-subtle"'));
});

test("a section learns from kit.editing whether the marketer is editing it", () => {
  const seen: boolean[] = [];
  const Probe = { schema: z.object({ id: z.string(), surface: z.string() }), render: ((_p: unknown, kit: Kit) => (seen.push(kit.editing), null)) as never };
  const config = makeConfig(garner(), { agentSections: { Probe } }) as Config;
  const render = (config.components.Probe as { render: (p: unknown) => ReactElement }).render;
  renderToStaticMarkup(render({ id: "p", surface: "page", puck: { isEditing: true } }));
  renderToStaticMarkup(render({ id: "p", surface: "page", puck: { isEditing: false } }));
  renderToStaticMarkup(render({ id: "p", surface: "page" }));
  assert.deepEqual(seen, [true, false, false]);
});
