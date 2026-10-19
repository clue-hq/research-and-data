// Plan 6 (rulings R2, R3): the header and footer drawn as the page's first and last sections, and the
// editor's combined page split back into the shell and the page.
import assert from "node:assert/strict";
import { test } from "node:test";
import { isShellEntry, pageWithShell, withEditedShellPage } from "../src/shell-entries";
import { SiteDocumentSchema, type SitePage } from "../src/site-document";
import { site as readSite } from "./fixtures/garner";

const stored = readSite("garner-syracuse");
const site = SiteDocumentSchema.parse({ id: "doc", title: "Garner", theme: {}, pages: stored.pages, shell: stored.shell, agent_sections: {} });
const home = site.pages["/"] as SitePage;

test("pageWithShell puts the header first and the footer last", () => {
  const drawn = pageWithShell(home, site.shell);
  assert.equal(drawn.content.length, home.content.length + 2);
  assert.deepEqual(drawn.content[0], site.shell!.header);
  assert.deepEqual(drawn.content.at(-1), site.shell!.footer);
  assert.deepEqual(drawn.content.slice(1, -1), home.content);
});

test("an absent or old-shape shell leaves the page as it is", () => {
  assert.equal(pageWithShell(home, null), home);
  const old = { header: { preparedFor: "x" }, footer: { legal: "y" } } as never;
  assert.equal(pageWithShell(home, old), home);
  assert.equal(isShellEntry({ preparedFor: "x" }), false);
  assert.equal(isShellEntry(site.shell!.header), true);
});

test("withEditedShellPage round-trips and splits an edit to the header out of the page", () => {
  assert.deepEqual(withEditedShellPage(site, "/", pageWithShell(home, site.shell)), site);
  const combined = pageWithShell(home, site.shell);
  const header = { ...combined.content[0], props: { ...combined.content[0].props, accountLine: "Built for Syracuse" } };
  const edited = withEditedShellPage(site, "/", { ...combined, content: [header, ...combined.content.slice(1)] });
  assert.equal((edited.shell!.header.props as unknown as { accountLine: string }).accountLine, "Built for Syracuse");
  assert.deepEqual(edited.pages["/"], home);
  assert.deepEqual(edited.shell!.footer, site.shell!.footer);
});
