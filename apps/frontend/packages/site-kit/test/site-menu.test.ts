// Plan 6 (ruling R8): the header's menu lists the site's pages, keyed by page so a key never moves.
import assert from "node:assert/strict";
import { test } from "node:test";
import { menuItems, menuKey, siteMenuPages } from "../src/site-menu";

const page = {};

test("the site's pages, home first, with their keys and default labels", () => {
  assert.deepEqual(siteMenuPages({ "/team": page, "/": page, "/roi-analysis": page }), [
    { route: "/", key: "menu._home", label: "Overview" },
    { route: "/roi-analysis", key: "menu.roi-analysis", label: "Roi analysis" },
    { route: "/team", key: "menu.team", label: "Team" },
  ]);
  assert.equal(menuKey("/"), "menu._home");
  assert.equal(menuKey("/team"), "menu.team");
});

test("a one-page site lists no pages", () => {
  assert.deepEqual(siteMenuPages({ "/": page }), []);
});

test("labels are renamed by page and extra links come after the pages", () => {
  const pages = siteMenuPages({ "/": page, "/team": page });
  assert.deepEqual(menuItems(pages, { menuLabels: { team: "Who we are" }, menuExtra: [{ label: "Pricing", href: "https://seller.example/pricing", newTab: true }] }), [
    { key: "menu._home", label: "Overview", href: "/", source: { kind: "page", route: "/" } },
    { key: "menu.team", label: "Who we are", href: "/team", source: { kind: "page", route: "/team" } },
    { key: "menu._0", label: "Pricing", href: "https://seller.example/pricing", newTab: true, source: { kind: "extra", index: 0 } },
  ]);
  assert.deepEqual(menuItems([], { menuExtra: [{ label: "Pricing", href: "/" }] }).map((item) => item.key), ["menu._0"]);
});
