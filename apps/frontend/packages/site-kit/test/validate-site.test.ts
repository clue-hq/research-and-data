// The validator as the harness calls it: the site's files handed over (not read from a
// workspace), missing files named as the spike named them, and the CLI that imports a site's
// agent-written sections from their module paths.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { validateSite } from "../src/validate";
import { garner, site as readSite } from "./fixtures/garner";
import { schema as quoteSchema } from "./fixtures/section-example";

const site = readSite("garner-syracuse");
const brand = garner();
const pages = { "/": site.pages["/"], "/analysis": site.pages["/analysis"] };

test("a missing page.json or shell.json says it does not exist yet", () => {
  const result = validateSite({ pages: {}, shell: null }, brand, {});
  assert.equal(result.valid, false);
  assert.deepEqual(
    result.errors.map((e) => e.split(":")[0]),
    ["page.json", "shell.json"],
  );
  assert.ok(result.errors.every((e) => e.includes("does not exist yet; create it with write_file")));
});

test("a file given as its text is parsed; text that is not JSON names the file", () => {
  const asText = { "/": JSON.stringify(pages["/"]), "/analysis": JSON.stringify(pages["/analysis"]) };
  assert.deepEqual(validateSite({ pages: asText, shell: JSON.stringify(site.shell) }, brand, {}), { valid: true, errors: [] });
  const broken = validateSite({ pages: { ...asText, "/analysis": "{ not json" }, shell: site.shell }, brand, {});
  assert.ok(broken.errors.some((e) => e.startsWith("pages/analysis.json: not valid JSON")), broken.errors.join("\n"));
});

test("the CLI checks an agent section against its stored props JSON Schema, never importing it", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const run = (page: unknown) =>
    JSON.parse(
      execFileSync(process.execPath, ["--import", "tsx", "bin/validate-site.ts"], {
        cwd: root,
        input: JSON.stringify({
          files: { pages: { ...pages, "/": page }, shell: site.shell },
          brand,
          agentSectionSchemas: { QuoteBand: z.toJSONSchema(quoteSchema) },
        }),
      }).toString(),
    );
  const withQuote = (surface: string) => {
    const page = structuredClone(pages["/"]);
    page.content.push({ type: "QuoteBand", props: { id: "quote", surface, quote: "Fewer surprises.", attribution: "A buyer" } });
    return page;
  };
  assert.deepEqual(run(withQuote("page")), { valid: true, errors: [] });
  const refused = run(withQuote("green"));
  assert.equal(refused.valid, false);
  assert.ok(refused.errors.some((e: string) => /^page\.content\.\d+\(quote\)\.surface/.test(e)), refused.errors.join("\n"));
});

test("a stored schema that cannot be read is named, not ignored", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const out = JSON.parse(
    execFileSync(process.execPath, ["--import", "tsx", "bin/validate-site.ts"], {
      cwd: root,
      input: JSON.stringify({ files: { pages, shell: site.shell }, brand, agentSectionSchemas: { Broken: { type: "no-such-type" } } }),
    }).toString(),
  );
  assert.equal(out.valid, false);
  assert.ok(out.errors.some((e: string) => e.startsWith("agent_sections.Broken: its stored props schema could not be read")), out.errors.join("\n"));
});

// Plan 5 (ruling R2, R8): alt texts are plain text of at most 300 characters.
test("alt texts are plain text of at most 300 characters, on our images, the shell's logos and copied images", () => {
  const MESSAGE = "alt text is plain text of at most 300 characters, with no line breaks or control characters";
  const withAlts = (feature: string, header: string, clone: Record<string, string>) => {
    const home = structuredClone(site.pages["/"]);
    const analysis = structuredClone(site.pages["/analysis"]);
    analysis.content[0].props.imageAlt = feature;
    const hero = home.content.find((item: { type: string }) => item.type === "ClonedSection")!;
    hero.props.alts = clone;
    const shell = structuredClone(site.shell);
    shell.header.props.accountLogoAlt = header;
    shell.header.props.logoAlt = 'Garner "Health"';
    shell.footer.props.logoAlt = "Garner";
    return validateSite({ pages: { "/": home, "/analysis": analysis }, shell }, brand, {});
  };
  const ok = 'Dr. "Smith" & <team>';
  assert.deepEqual(withAlts(ok, ok, { "0.1": ok }), { valid: true, errors: [] });
  const bad = withAlts("x".repeat(301), "line\nbreak", { "0.1": "x".repeat(301) });
  assert.equal(bad.valid, false);
  for (const field of ["imageAlt", "accountLogoAlt", "alts.0.1"]) {
    assert.ok(bad.errors.some((error) => error.includes(field) && error.endsWith(MESSAGE)), `${field}: ${bad.errors.join("\n")}`);
  }
  const spanKey = withAlts("", "", { "0.1~2": "x" });
  assert.equal(spanKey.valid, false, spanKey.errors.join("\n"));
});

// Plan 6 (rulings R1, R10): the header and footer are section entries.
const ACCOUNT_LOGO = `/asset-store/${"a".repeat(64)}`;
const headerClone = (props: Record<string, unknown> = {}) => ({
  type: "ClonedSection",
  props: { id: "header", fragmentId: "frag_1f86b8d67557b66b", slots: {}, replacements: [], links: [], ...props },
});
const siteFooter = (props: Record<string, unknown> = {}) => ({
  type: "SiteFooter",
  props: { id: "footer", legal: "© 2026 Garner Health.", privacyHref: "", termsHref: "", ...props },
});
const check = (shell: unknown, extraPages: Record<string, unknown> = {}, agentSections = {}) =>
  validateSite({ pages: { ...pages, ...extraPages }, shell }, brand, agentSections, { siteImages: [], accountLogos: [ACCOUNT_LOGO] });

test("a shell of two section entries is valid", () => {
  assert.deepEqual(check({ header: headerClone(), footer: siteFooter() }), { valid: true, errors: [] });
});

test("the old shell shape is refused with how to fix it", () => {
  const result = check({ header: { preparedFor: "x", ctaLabel: "Go", ctaHref: "/" }, footer: { legal: "y" } });
  assert.deepEqual(result.errors, [
    'shell.json: the header and footer are sections: {"header": {"type": …, "props": {"id": "header", …}}, "footer": {…}} (building-with-puck skill)',
  ]);
});

test("shell ids and types are checked", () => {
  const wrongId = check({ header: headerClone({ id: "top" }), footer: siteFooter() });
  assert.ok(wrongId.errors.includes('shell.header.props.id: must be "header"'), wrongId.errors.join("\n"));
  const wrongType = check({ header: { type: "SiteFooter", props: { id: "header", legal: "x" } }, footer: siteFooter() });
  assert.ok(
    wrongType.errors.includes("shell.header.type: SiteFooter is the footer's; the header is SiteHeader, a ClonedSection or one of this site's sections"),
    wrongType.errors.join("\n"),
  );
  const home = structuredClone(pages["/"]);
  home.content.push({ type: "SiteHeader", props: { id: "header", accountLine: "x", ctaLabel: "Go", ctaHref: "/" } });
  const onPage = check({ header: headerClone(), footer: siteFooter() }, { "/": home });
  const at = `page.content.${home.content.length - 1}(header)`;
  assert.ok(onPage.errors.includes(`${at}.id: "header" and "footer" are the header's and footer's ids; use another id`), onPage.errors.join("\n"));
  assert.ok(onPage.errors.includes(`${at}.type: SiteHeader and SiteFooter belong in shell.json`), onPage.errors.join("\n"));
});

test("shell entries get every page item check", () => {
  const result = check({
    header: headerClone({
      slots: { nope: "x", image: "/asset-store/" + "b".repeat(64), cta_href: "/nowhere" },
      menuExtra: [{ label: "Pricing", href: "/pricing" }],
    }),
    footer: siteFooter(),
  });
  const at = "shell.header";
  assert.ok(result.errors.some((e) => e.startsWith(`${at}.slots.nope: "nope" is not a slot of frag_1f86b8d67557b66b`)), result.errors.join("\n"));
  assert.ok(result.errors.some((e) => e.startsWith(`${at}.slots.image: image "/asset-store/`)), result.errors.join("\n"));
  assert.ok(result.errors.some((e) => e.startsWith(`${at}.slots.cta_href: links to /nowhere`)), result.errors.join("\n"));
  assert.ok(result.errors.some((e) => e.startsWith(`${at}.menuExtra.0.href: links to /pricing`)), result.errors.join("\n"));
});

test("account logos are allowed in any shell image, never on a page", () => {
  assert.equal(check({ header: headerClone({ slots: { image: ACCOUNT_LOGO } }), footer: siteFooter() }).valid, true);
  const home = structuredClone(pages["/"]);
  home.content.push({ ...headerClone({ id: "logo-band", slots: { image: ACCOUNT_LOGO } }) });
  const onPage = check({ header: headerClone(), footer: siteFooter() }, { "/": home });
  assert.ok(onPage.errors.some((e) => e.includes(`(logo-band).slots.image: image "${ACCOUNT_LOGO}"`)), onPage.errors.join("\n"));
});

test("sticky and overlay are the header root's", () => {
  assert.equal(check({ header: headerClone({ _edits: { root: { sticky: true, overlay: true } } }), footer: siteFooter() }).valid, true);
  const misplaced = check({
    header: headerClone({ _edits: { "0.1": { sticky: true } } }),
    footer: siteFooter({ _edits: { root: { overlay: true } } }),
  });
  assert.ok(misplaced.errors.includes("shell.header._edits.0.1: sticky and overlay are for the header itself (its root)"), misplaced.errors.join("\n"));
  assert.ok(misplaced.errors.includes("shell.footer._edits.root: sticky and overlay are for the header itself (its root)"), misplaced.errors.join("\n"));
  const home = structuredClone(pages["/"]);
  home.content[0].props._edits = { root: { sticky: true } };
  const onPage = check({ header: headerClone(), footer: siteFooter() }, { "/": home });
  assert.ok(onPage.errors.some((e) => e.endsWith("._edits.root: sticky and overlay are for the header itself (its root)")), onPage.errors.join("\n"));
});

test("an agent section may be the header", () => {
  const agent = { SiteHeaderAcme: { schema: z.object({ id: z.string(), surface: z.string(), line: z.string() }).strict() } };
  const shell = { header: { type: "SiteHeaderAcme", props: { id: "header", surface: "page", line: "For Syracuse" } }, footer: siteFooter() };
  assert.deepEqual(check(shell, {}, agent), { valid: true, errors: [] });
});

test("the fallback header and footer take the plan 6 props", () => {
  const shell = {
    header: { type: "SiteHeader", props: { id: "header", accountLine: "Built for <strong>Syracuse</strong>", ctaLabel: "Book", ctaHref: "/analysis", menuLabels: { _home: "Overview", analysis: "The analysis" } } },
    footer: siteFooter({ privacyLabel: "Privacy", termsLabel: "Terms of use" }),
  };
  assert.deepEqual(check(shell), { valid: true, errors: [] });
  const old = check({ header: { type: "SiteHeader", props: { id: "header", preparedFor: "x", ctaLabel: "Go", ctaHref: "/" } }, footer: siteFooter() });
  assert.ok(old.errors.some((e) => e.startsWith("shell.header.")), old.errors.join("\n"));
});
