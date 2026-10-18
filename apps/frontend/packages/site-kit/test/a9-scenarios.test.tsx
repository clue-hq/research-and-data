// Wave 2 A9 business-logic scenarios: site-kit over the kit the extraction produced (founder ruling
// 2026-10-13). Each scenario drives site-kit's real entry points the way the site agent, the editor and
// the published route do: a whole multi-page site through validateSite and every section's real render,
// an agent section through the real lint, brand.md through the real catalog.
//
// Kits: the committed `probe.minted` (Garner's kit + everything the real probe measured on
// style_states.html, minted by the real code, with brief recipes for its buttons and card), and — when
// A9_SCENARIO_KIT names it — the kit detail the Python scenario read back from `GET /brand-kits/{id}`
// after a real keyless extraction (subsystems/clue-design/apps/api/tests/test_a9_scenarios.py,
// A9_SCENARIO_KIT_OUT). That kit has no brief (keyless), so by founder ruling Q-A9-2 it offers no looks.
//
// A scenario that exposes a real defect is kept as a skipped test named "KNOWN DEFECT: …" holding the
// strict assertion. A9_PROVE_DEFECTS=1 runs those too, so each one can be seen failing (and noticed
// when a fix makes it pass).
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { Fragment, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { parse } from "node-html-parser";
import { z } from "zod";
import { brandData, type BrandData } from "../src/brand";
import { isSafeIconSvg, tokenGroups } from "../src/brand-values";
import { buildCatalog } from "../src/catalog";
import { lint, lintOptionsFor } from "../src/check-section";
import { fillClone } from "../src/clone";
import { makeConfig } from "../src/config";
import { buttonLooks, cardLooks, measuredComponents, motionClassNames } from "../src/looks";
import { surfaceClass } from "../src/sections";
import { surfaceChoices } from "../src/surfaces";
import { tailwindThemeCss, themeCss } from "../src/theme";
import { validateSite } from "../src/validate";
import { kitBrand } from "./fixtures/kits";

// --- the kits ---------------------------------------------------------------------------------

const SCENARIO_KIT = process.env.A9_SCENARIO_KIT;
/** A KNOWN DEFECT test's skip: its reason, unless A9_PROVE_DEFECTS=1 asks to run it. */
const defect = (reason: string): string | false => (process.env.A9_PROVE_DEFECTS === "1" ? false : reason);
const NO_SCENARIO_KIT =
  "A9_SCENARIO_KIT is not set to the kit detail test_a9_scenarios.py writes (run it with A9_SCENARIO_KIT_OUT=<path>)";

function extractedBrand(): BrandData | null {
  if (!SCENARIO_KIT || !fs.existsSync(SCENARIO_KIT)) return null;
  const detail = JSON.parse(fs.readFileSync(SCENARIO_KIT, "utf-8")) as { brand_kit_json: Record<string, unknown> };
  return brandData({ slug: "a9-extracted", kit: detail.brand_kit_json, fonts: [], kitAssets: {}, clones: [] });
}

const BRANDS: [string, () => BrandData | null][] = [
  ["probe.minted", () => kitBrand("probe.minted")],
  ["the extracted kit", extractedBrand],
];

// --- a whole site -----------------------------------------------------------------------------

type Item = { type: string; props: Record<string, unknown> };
type Page = { root: { props: { title: string } }; content: Item[] };
type Shell = { header: Item; footer: Item };
type Site = { pages: Record<string, Page>; shell: Shell; looks: string[]; surfaces: string[] };

/** Every one of our section types on every surface the brand has, one page per button look (the
 * home page with the standard button), a shell whose nav reaches every page. */
function fullSite(brand: BrandData): Site {
  const looks = ["", ...buttonLooks(brand).map((look) => look.name)];
  const surfaces = surfaceChoices(brand).map((choice) => choice.value);
  const pages: Record<string, Page> = {};
  looks.forEach((look, i) => {
    const route = i === 0 ? "/" : `/look-${i}`;
    const content: Item[] = surfaces.flatMap((surface, j) => [
      { type: "StatsBand", props: {
        id: `stats-${j}`, surface, align: j % 2 ? "center" : "left", eyebrow: "What changed", heading: "A headline about the result",
        intro: "One plain sentence.", stats: Array.from({ length: (j % 4) + 1 }, (_, k) => ({ value: `${k + 7}%`, label: "What the number means" })),
        source: "Source: the seller's study",
      } },
      { type: "FeatureSplit", props: {
        id: `split-${j}`, surface, eyebrow: "Why it matters", heading: "What this does for them",
        headingRole: (["display", "headline", "title"] as const)[j % 3], body: "One or two plain sentences.", image: "",
        imageSide: j % 2 ? "right" : "left", buttonLabel: "Book a demo", buttonHref: "/", buttonLook: look,
      } },
      { type: "ProofCard", props: {
        id: `proof-${j}`, surface, kicker: "Acme Health", metric: "13%", metricLabel: "fewer escalations", heading: "What they did",
        body: "A sentence.", source: "Source line", linkLabel: "Read the study", linkHref: "/",
      } },
      { type: "CtaBand", props: {
        id: `cta-${j}`, surface, heading: "The one next step", body: "A sentence.", buttonLabel: "Get started", buttonHref: "/", buttonLook: look,
      } },
    ]);
    pages[route] = { root: { props: { title: route } }, content };
  });
  const shell: Shell = {
    header: { type: "SiteHeader", props: {
      id: "header", accountLine: "Prepared for Acme Health", accountLogo: "", ctaLabel: "Book a demo", ctaHref: "/", ctaLook: looks[1] ?? "",
      menuExtra: looks.slice(1, 7).map((_, i) => ({ label: `Look ${i + 1}`, href: `/look-${i + 1}` })),
    } },
    footer: { type: "SiteFooter", props: { id: "footer", legal: "© The seller", privacyHref: "/", termsHref: "/" } },
  };
  return { pages, shell, looks, surfaces };
}

type Renderable = { render: (props: Record<string, unknown>) => ReactNode };
type AnyConfig = { root: Renderable; components: Record<string, Renderable> };

/** Every page through the published config's root (the shell around it), and the shell's own two
 * components through the shell-mode config. */
function renderSite(brand: BrandData, site: Site): string {
  const config = makeConfig(brand, { cloneHtml: fillClone, shell: { header: site.shell.header.props, footer: site.shell.footer.props } as never, basePath: "/s/a9" }) as unknown as AnyConfig;
  const pages = Object.values(site.pages).map((page) => renderToStaticMarkup(
    <>{config.root.render({
      title: page.root.props.title,
      children: page.content.map((item, k) => (
        <Fragment key={k}>{config.components[item.type].render({ ...item.props, puck: { isEditing: false } })}</Fragment>
      )),
    })}</>,
  ));
  const shellConfig = makeConfig(brand, { cloneHtml: fillClone, mode: "shell" }) as unknown as AnyConfig;
  const shell = renderToStaticMarkup(
    <>{shellConfig.root.render({ children: <>
      {shellConfig.components.SiteHeader.render(site.shell.header.props)}
      {shellConfig.components.SiteFooter.render(site.shell.footer.props)}
    </> })}</>,
  );
  return [...pages, shell].join("\n");
}

/** Layout: the same list as test/style-literals.test.ts's STRUCTURE (where things go, never how the
 * brand looks). */
const STRUCTURE = [
  /^(flex|inline-flex|grid|block|inline-block|inline|hidden|contents)$/,
  /^flex-(row|col|wrap|1|none)$/, /^(grow|shrink-0|min-w-0)$/, /^self-(start|center|end)$/,
  /^grid-cols-(\d+|\[[0-9a-z(),_.]+\])$/, /^order-\d+$/,
  /^items-(start|center|end|baseline|stretch)$/, /^justify-(start|center|end|between)$/,
  /^text-(left|center|right)$/, /^(truncate|whitespace-nowrap|sr-only)$/,
  /^(w|h)-(full|auto)$/, /^max-w-\[\d+ch\]$/, /^mx-auto$/,
  /^(relative|absolute|inset-0|overflow-hidden)$/, /^object-(cover|contain)$/,
  /^\[&>\*\]:mx-auto$/, /^\[&_dd\]:mx-auto$/,
  /^lumen-fragment$/,
  /^clue-section$/,
];
const RESPONSIVE = /^(sm|md|lg|xl|2xl):/;

/** Every class the markup uses that neither theme stylesheet defines and that is not layout. */
function orphanClasses(brand: BrandData, markup: string): string[] {
  const css = themeCss(brand);
  const themeClasses = new Set([...css.matchAll(/\.(-?[_a-zA-Z][_a-zA-Z0-9-]*)/g)].map((m) => m[1]));
  const vars = new Set([...tailwindThemeCss(brand).matchAll(/--([a-z0-9-]+):/g)].map((m) => m[1]));
  const utility = (cls: string): boolean => {
    let m: RegExpExecArray | null;
    if ((m = /^bg-(.+)$/.exec(cls))) return vars.has(`color-${m[1]}`);
    if ((m = /^text-(.+)$/.exec(cls))) return vars.has(`color-${m[1]}`) || vars.has(`text-${m[1]}`);
    if ((m = /^font-(.+)$/.exec(cls))) return vars.has(`font-${m[1]}`);
    if ((m = /^rounded-(.+)$/.exec(cls))) return vars.has(`radius-${m[1]}`);
    if ((m = /^(?:p|m)[xytrbl]?-(.+)$/.exec(cls)) || (m = /^gap(?:-[xy])?-(.+)$/.exec(cls))) return vars.has(`spacing-${m[1]}`);
    return false;
  };
  const used = new Set(
    parse(markup).querySelectorAll("[class]").flatMap((el) => (el.getAttribute("class") ?? "").split(/\s+/).filter(Boolean)),
  );
  return [...used].filter((cls) => {
    const bare = cls.replace(RESPONSIVE, "");
    if (STRUCTURE.some((pattern) => pattern.test(bare))) return false;
    if (bare.startsWith("brand-")) return !themeClasses.has(bare);
    return !utility(bare);
  }).sort();
}

for (const [name, load] of BRANDS) {
  const brand = load();
  const skip = brand ? false : NO_SCENARIO_KIT;

  test(`B1 ${name}: a full multi-page site — every section type, every look, every surface — validates`, { skip }, () => {
    const site = fullSite(brand!);
    assert.ok(site.surfaces.length >= 6 + 1, `the six and the brand's others: ${site.surfaces.join(", ")}`);
    assert.ok(site.surfaces.some((surface) => /^band-[0-9a-f]{6}$/.test(surface)), "a band surface is a choice");
    const result = validateSite({ pages: site.pages, shell: site.shell }, brand!, {});
    assert.deepEqual(result.errors, []);
    assert.equal(result.valid, true);
  });

  test(`B1 ${name}: rendering the whole site draws every look and every surface by the brand's own classes`, { skip }, () => {
    const site = fullSite(brand!);
    const markup = renderSite(brand!, site);
    for (const look of buttonLooks(brand!)) assert.ok(markup.includes(`class="brand-btn brand-look-${look.index}"`), look.name);
    for (const choice of surfaceChoices(brand!)) assert.ok(markup.includes(surfaceClass(choice.value)), choice.value);
  });

  test(`B1 ${name}: every rendered class is defined by themeCss/tailwindThemeCss or is layout`, { skip }, () => {
    assert.deepEqual(orphanClasses(brand!, renderSite(brand!, fullSite(brand!))), []);
  });
}

// --- agent sections ---------------------------------------------------------------------------

/** An agent section in the shape the writing-a-section skill teaches, with prose that says
 * "transition" and "ease-of-use" in its defaults and its text. */
function section(parts: { buttonLook?: string; cardLook?: string; motion?: string; className?: string; buttonAttr?: string }): string {
  const button = parts.buttonAttr ?? (parts.buttonLook ? ` look="${parts.buttonLook}"` : "");
  return `import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.string(),
  heading: z.string().default("Make the transition to value-based care"),
  note: z.string().default("Built for ease-of-use from the first week."),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <h2 className="font-headline text-headline brand-ink-headline${parts.motion ? ` ${parts.motion}` : ""}">{props.heading}</h2>
      <p className="mt-stack-default font-body text-body brand-ink-body${parts.className ? ` ${parts.className}` : ""}">{props.note} The transition takes a week; ease-of-use is the point.</p>
      <kit.Card${parts.cardLook ? ` look="${parts.cardLook}"` : ""}><p className="font-body text-body">Inside the card</p></kit.Card>
      <div className="mt-stack-loose">
        <kit.Button label="Book a demo" href="/" surface={props.surface}${button} />
      </div>
    </kit.Shell>
  );
}
`;
}

test("B2 probe.minted: an agent section with a real look, a real card look, a brand motion class and prose lints clean", () => {
  const brand = kitBrand("probe.minted");
  const options = lintOptionsFor(brand);
  const [buttonLook] = buttonLooks(brand);
  const [cardLook] = cardLooks(brand);
  const [motion] = motionClassNames(brand);
  assert.ok(buttonLook && cardLook && motion, "probe.minted has a look, a card look and a motion class");
  for (const look of buttonLooks(brand)) {
    for (const motionClass of motionClassNames(brand)) {
      assert.deepEqual(lint(section({ buttonLook: look.name, cardLook: cardLook.name, motion: motionClass }), options), [], `${look.name} ${motionClass}`);
    }
  }
});

test("B2 probe.minted: an unknown look, an unknown card look, an unknown brand motion class and className=\"transition\" are refused", () => {
  const brand = kitBrand("probe.minted");
  const options = lintOptionsFor(brand);
  const good = { buttonLook: buttonLooks(brand)[0].name, cardLook: cardLooks(brand)[0].name, motion: motionClassNames(brand)[0] };
  const refused = (parts: Parameters<typeof section>[0], why: RegExp) => {
    const errors = lint(section({ ...good, ...parts }), options);
    assert.ok(errors.some((e) => why.test(e)), `${JSON.stringify(parts)}: ${errors.join(" | ")}`);
  };
  refused({ buttonLook: "solid.123456" }, /look "solid\.123456" on kit\.Button is not one of this brand's button styles/);
  refused({ cardLook: "solid.123456" }, /look "solid\.123456" on kit\.Card is not one of this brand's card styles/);
  refused({ motion: "brand-motion-wobble" }, /class "brand-motion-wobble" is not one of this brand's motion classes/);
  refused({ className: "transition" }, /class "transition" is motion of your own/);
});

test("B2 probe.minted: an unknown look written in braces (look={\"solid.123456\"}) is refused too", () => {
  const brand = kitBrand("probe.minted");
  const errors = lint(section({ cardLook: cardLooks(brand)[0].name, buttonAttr: ' look={"solid.123456"}' }), lintOptionsFor(brand));
  assert.ok(errors.some((e) => /solid\.123456/.test(e)), errors.join(" | "));
});

test("B2 probe.minted: prose that says \"style:\" is not refused as an inline style", () => {
  const brand = kitBrand("probe.minted");
  const source = section({ buttonLook: buttonLooks(brand)[0].name }).replace("Built for ease-of-use from the first week.", "Leadership style: hands-on.");
  assert.deepEqual(lint(source, lintOptionsFor(brand)), []);
});

test("B2 the extracted kit: a briefless kit lints prose and its motion clean, and offers no looks (founder Q-A9-2)", { skip: extractedBrand() ? false : NO_SCENARIO_KIT }, () => {
  const brand = extractedBrand()!;
  const options = lintOptionsFor(brand);
  assert.equal(measuredComponents(brand)?.styles?.filter((s) => s.component === "button").length, 5, "five measured button styles");
  assert.deepEqual(options.buttonLooks, [], "but no brief recipe names them, so none is a look");
  assert.ok(options.motions?.length, "its measured motion is offered");
  for (const motionClass of options.motions ?? []) assert.deepEqual(lint(section({ motion: motionClass }), options), []);
  assert.ok(lint(section({ buttonLook: "solid.047464" }), options).some((e) => e.includes("is not one of this brand's button styles; the styles are none")));
});

// --- brand.md ---------------------------------------------------------------------------------

const tableColumn = (md: string, heading: string): string[] => {
  const block = md.split(`## ${heading}\n`)[1]?.split("\n## ")[0] ?? "";
  return block.split("\n").filter((line) => line.startsWith("| ") && !line.startsWith("|---") && !line.startsWith("| choice ") && !line.startsWith("| look "))
    .map((line) => line.split("|")[1].trim());
};

function allTokenNames(brand: BrandData): Set<string> {
  return new Set(Object.values(tokenGroups(brand)).flatMap((entries) => Object.keys(entries ?? {})));
}

for (const [name, load] of BRANDS) {
  const brand = load();
  const skip = brand ? false : NO_SCENARIO_KIT;

  test(`B3 ${name}: every (token.name) brand.md writes is a token of the kit`, { skip }, () => {
    const md = buildCatalog(brand!, "Seller")["brand/brand.md"];
    const names = [...md.matchAll(/\(([a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+)(?=[,)])/g)].map((m) => m[1]);
    assert.ok(names.length > 20, `brand.md names tokens: ${names.length}`);
    const known = allTokenNames(brand!);
    assert.deepEqual([...new Set(names.filter((n) => !known.has(n)))], []);
    const roles = md.split("## Surfaces\n")[1].split("\n## ")[0].split("\n").filter((l) => /^\| [a-z]/.test(l) && !l.startsWith("| choice")).map((l) => l.split("|")[3].trim());
    assert.deepEqual(roles.filter((role) => !known.has(role)), [], "every kit name in the surfaces table");
  });

  test(`B3 ${name}: every surface and every look brand.md offers is one the validator accepts`, { skip }, () => {
    const md = buildCatalog(brand!, "Seller")["brand/brand.md"];
    const surfaces = tableColumn(md, "Surfaces");
    assert.deepEqual(surfaces, surfaceChoices(brand!).map((c) => c.value), "the table lists every choice");
    const looks = tableColumn(md, "Buttons").filter((cell) => cell !== "(none)");
    const cards = tableColumn(md, "Cards").filter((cell) => cell !== "(none)");
    const quoted = [...md.matchAll(/kit\.(?:Button|Card) look="([^"]+)"/g)].map((m) => m[1]);
    const Promo = { schema: z.object({ id: z.string(), surface: z.string(), look: z.string().optional(), cardLook: z.string().optional() }).strict() };
    const pages: Record<string, Page> = { "/": { root: { props: { title: "Home" } }, content: [
      ...surfaces.flatMap((surface, i) => [
        { type: "CtaBand", props: { id: `cta-${i}`, surface, heading: "H", body: "", buttonLabel: "Go", buttonHref: "/", buttonLook: looks[i % Math.max(1, looks.length)] ?? "" } },
        { type: "Promo", props: { id: `promo-${i}`, surface, ...(looks.length ? { look: looks[i % looks.length] } : {}), ...(cards.length ? { cardLook: cards[i % cards.length] } : {}) } },
      ]),
      ...looks.map((look, i) => ({ type: "FeatureSplit", props: { id: `split-${i}`, surface: "page", heading: "H", body: "B", buttonLabel: "Go", buttonHref: "/", buttonLook: look } })),
      ...cards.map((cardLook, i) => ({ type: "Promo", props: { id: `card-${i}`, surface: "page", cardLook } })),
    ] } };
    const shell: Shell = {
      header: { type: "SiteHeader", props: { id: "header", accountLine: "Acme", accountLogo: "", ctaLabel: "Go", ctaHref: "/", ctaLook: looks[0] ?? "" } },
      footer: { type: "SiteFooter", props: { id: "footer", legal: "©", privacyHref: "", termsHref: "" } },
    };
    const result = validateSite({ pages, shell }, brand!, { Promo });
    assert.deepEqual(result.errors, []);
    for (const look of quoted) assert.ok([...buttonLooks(brand!), ...cardLooks(brand!)].some((l) => l.name === look), `brand.md's example look ${look}`);
    const motionTable = (md.split("## Motion\n")[1] ?? "").split("\n## ")[0];
    const motions = [...motionTable.matchAll(/\| `(brand-motion-[a-z0-9-]+)` \|/g)].map((m) => m[1]);
    assert.deepEqual(motions, motionClassNames(brand!), "the Motion table lists exactly the classes the lint accepts");
  });
}

// --- the icon re-check site-kit draws with -----------------------------------------------------

test("site-kit's icon re-check (isSafeIconSvg) refuses an event handler after a slash, a quote or a tab, as the engine does", () => {
  for (const markup of [
    '<svg/onload="alert(1)"></svg>',
    '<svg a="1"onload="alert(1)"></svg>',
    '<svg\tonload="alert(1)"></svg>',
    '<svg\nonload="alert(1)"></svg>',
  ]) assert.equal(isSafeIconSvg(markup), false, JSON.stringify(markup));
});

/** The icon-markup vectors the engine (brand_style_tokens.rs) and ingestion (svg_ok) are tested against. */
const ICON_SVG_CASES = JSON.parse(fs.readFileSync(
  new URL("../../../../../subsystems/clue-design/crates/lumen-core/fixtures/brand/icon_svg_cases.json", import.meta.url),
  "utf-8",
)) as { accept: string[]; refuse: { markup: string; why: string }[] };

test("site-kit's icon re-check accepts exactly the engine's icon vectors", () => {
  const wrong = [
    ...ICON_SVG_CASES.accept.filter((markup) => !isSafeIconSvg(markup)).map((markup) => `refused: ${JSON.stringify(markup)}`),
    ...ICON_SVG_CASES.refuse.filter(({ markup }) => isSafeIconSvg(markup)).map(({ markup, why }) => `accepted (${why}): ${JSON.stringify(markup)}`),
  ];
  assert.deepEqual(wrong, []);
});

test("site-kit's icon re-check refuses the brief's four hostile forms as drawn by a space-separated handler, a script, a use and an href", () => {
  for (const markup of [
    '<svg onload="alert(1)"></svg>',
    '<svg><script>alert(1)</script></svg>',
    '<svg><use href="#a"></use></svg>',
  ]) assert.equal(isSafeIconSvg(markup), false, markup);
  assert.equal(isSafeIconSvg('<svg width="12" height="12"><path d="M1 6h9"></path></svg>'), true);
});
