// Wave 2 A9 business-logic scenario B4: the Brand page reads a measured kit the way a published site
// draws it (founder ruling 2026-10-13). The page's mapping (`toMeasuredBrand`) runs over the detail DTO
// exactly as `GET /brand-kits/{id}` serves it, and every value a sample shows is compared with what
// site-kit draws for the same look — `partsFromSlots` for each slot, and for buttons the CSS rule the
// published theme (`themeCss`) actually ships for that look and state.
//
// Kits: the committed brand-kit.measured.json (probe.minted through the design API's detail DTO) and,
// when A9_SCENARIO_KIT names it, the detail a real keyless extraction served
// (subsystems/clue-design/apps/api/tests/test_a9_scenarios.py, A9_SCENARIO_KIT_OUT). Kept in the app
// because site-kit may not import the app.
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { buttonLooks, themeCss } from "@clue/site-kit";
import { brandData, partsFromSlots, type BrandData, type MeasuredRecipe, type Part } from "@clue/site-kit/brand-view";
import { MEASURED_BRAND_KIT } from "../data/__fixtures__/harvest";
import { BrandKitDetailSchema } from "./brand-kit";
import { toMeasuredBrand } from "./measured-brand";
import type { MeasuredBrandView, SampleState } from "./measured-view";

const SCENARIO_KIT = process.env.A9_SCENARIO_KIT;
const NO_SCENARIO_KIT =
  "A9_SCENARIO_KIT is not set to the kit detail test_a9_scenarios.py writes (run it with A9_SCENARIO_KIT_OUT=<path>)";

type Detail = { brand_kit: { id: string }; brand_kit_json: Record<string, unknown> };
const KITS: [string, () => Detail | null][] = [
  ["probe.minted (brand-kit.measured.json)", () => MEASURED_BRAND_KIT as Detail],
  ["the extracted kit", () => (SCENARIO_KIT && fs.existsSync(SCENARIO_KIT) ? (JSON.parse(fs.readFileSync(SCENARIO_KIT, "utf-8")) as Detail) : null)],
];

/** theme.ts's CSS_OF: the property each drawn part is written as. */
const CSS_OF: Record<Part, string> = {
  fill: "background-color", label: "color", border: "border-color", borderWidth: "border-width", borderStyle: "border-style",
  radius: "border-radius", padding: "padding", height: "min-height", gap: "gap", fontFamily: "font-family",
  fontSize: "font-size", fontWeight: "font-weight", lineHeight: "line-height", tracking: "letter-spacing",
  case: "text-transform", decoration: "text-decoration-line", decorationThickness: "text-decoration-thickness",
  underlineOffset: "text-underline-offset", shadow: "box-shadow", opacity: "opacity", transform: "transform",
  filter: "filter", cursor: "cursor", outlineColor: "outline-color", outlineWidth: "outline-width",
  outlineStyle: "outline-style", outlineOffset: "outline-offset", iconColor: "color", iconTransform: "transform",
  iconOpacity: "opacity",
};
const ICON_PARTS = new Set(["iconColor", "iconTransform", "iconOpacity"]);
const STATE_SELECTOR: Record<Exclude<SampleState, "rest">, string> = {
  hover: ":hover", pressed: ":active", focus: ":focus-visible", disabled: '[aria-disabled="true"]',
};

/** One rule's declarations in the theme, by its exact selector; null when the theme writes none. */
function rule(css: string, selector: string): Record<string, string> | null {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`(?:^|[{}\\n])${escaped}\\{([^}]*)\\}`).exec(css);
  if (!match) return null;
  return Object.fromEntries(match[1].split(";").filter(Boolean).map((d) => [d.slice(0, d.indexOf(":")), d.slice(d.indexOf(":") + 1)]));
}

/** A drawn value, or the surface-swap wrapper the theme puts around it (`var(--bs-<id>-<part>,<value>)`). */
const draws = (declared: string | undefined, value: string) =>
  declared === value || (!!declared && declared.startsWith("var(--bs-") && declared.endsWith(`,${value})`));

for (const [name, load] of KITS) {
  const raw = load();
  const skip = raw ? false : NO_SCENARIO_KIT;
  // The page reads the kit through its schema; a published site reads the stored kit as served.
  const detail = raw ? BrandKitDetailSchema.parse(raw) : null;
  const view = detail ? (toMeasuredBrand(detail) as MeasuredBrandView) : null;
  const site: BrandData | null = raw ? brandData({ slug: raw.brand_kit.id, kit: raw.brand_kit_json, fonts: [], kitAssets: {}, clones: [] }) : null;
  const measured = (raw?.brand_kit_json as { measured_components?: { styles: MeasuredRecipe[] } } | undefined)?.measured_components?.styles ?? [];

  // The schema keeps "every group that names one" (brand-kit.ts, Task X6): the groups a measured slot
  // can name. `aliases`, `effects` and token `assets` are not among them and are stripped by design.
  test(`B4 ${name}: the Brand page's kit read keeps the measured section and every token of every group a measured style can name`, { skip }, () => {
    const served = raw!.brand_kit_json as { tokens: Record<string, Record<string, unknown>>; measured_components: unknown };
    const read = detail!.brand_kit_json as unknown as { tokens: Record<string, Record<string, unknown> | null>; measured_components: unknown };
    assert.deepEqual(read.measured_components, served.measured_components);
    const named = ["colors", "typography", "numbers", "spacing", "radii", "stroke_widths", "opacity", "shadows", "styles"];
    const kept = (tokens: Record<string, Record<string, unknown> | null>) =>
      Object.fromEntries(named.map((group) => [group, Object.entries(tokens[group] ?? {}).filter(([, entry]) => entry !== null).map(([key]) => key).sort()]));
    assert.deepEqual(kept(read.tokens), kept(served.tokens), "no token of those groups dropped (or nulled) by the page's schema");
    const names = new Set(named.flatMap((group) => Object.keys(read.tokens[group] ?? {})));
    const referenced = measured.flatMap((style) => [
      ...Object.values(style.rest), ...Object.values(style.states ?? {}).flatMap((slots) => Object.values(slots ?? {})),
      ...style.motion.flatMap((step) => [step.duration, step.easing, step.delay].filter((n): n is string => !!n)),
      ...(style.icon ? [style.icon.token] : []),
    ]);
    assert.deepEqual(referenced.filter((token) => !names.has(token)), [], "every token a measured style names survives the read");
  });

  test(`B4 ${name}: every measured style has its Components entry, buttons named as the editor names them`, { skip }, () => {
    const shown = view!.groups.flatMap((group) => group.styles.map((style) => style.id)).sort();
    assert.deepEqual(shown, measured.map((style) => `${style.component}:${style.variant}`).sort());
    for (const style of view!.groups.find((group) => group.id === "buttons")?.styles ?? []) {
      const look = buttonLooks(site!).find((l) => l.name === style.variant);
      if (look) assert.equal(style.name, look.label, `${style.variant}: the Brand page and the Button style field name it alike (DR-A9-10)`);
    }
  });

  test(`B4 ${name}: every sample's values are site-kit's own reading of the same slots`, { skip }, () => {
    for (const style of view!.groups.flatMap((group) => group.styles)) {
      const recipe = measured.find((r) => `${r.component}:${r.variant}` === style.id)!;
      for (const sample of style.samples) {
        const slots = sample.state === "rest" ? recipe.rest : recipe.states?.[sample.state];
        const drawn = partsFromSlots(site!, slots);
        for (const value of sample.values) {
          const where = `${style.id} ${sample.state} ${value.label}`;
          if (value.part === "font") {
            assert.equal(value.token, drawn.tokens.fontFamily, where);
            continue;
          }
          assert.equal(value.value, drawn.parts[value.part as Part], where);
          assert.equal(value.token, drawn.tokens[value.part as Part], where);
        }
      }
    }
  });

  test(`B4 ${name}: every button sample's value is what the published theme draws for that look and state`, { skip }, () => {
    const css = themeCss(site!);
    const looks = buttonLooks(site!);
    const missing: string[] = [];
    let compared = 0;
    for (const style of view!.groups.find((group) => group.id === "buttons")?.styles ?? []) {
      const look = looks.find((l) => l.name === style.variant);
      if (!look) continue; // no brief recipe names it (founder Q-A9-2): the site cannot draw it, so there is nothing to compare
      const base = `.brand-btn.brand-look-${look.index}`;
      for (const sample of style.samples) {
        const selector = sample.state === "rest" ? base : `${base}${STATE_SELECTOR[sample.state]}`;
        const box = rule(css, selector) ?? {};
        const icon = rule(css, `${selector} .brand-btn-icon`) ?? {};
        const drawn = partsFromSlots(site!, sample.state === "rest" ? look.measured?.rest : look.measured?.states?.[sample.state]);
        for (const value of sample.values) {
          const parts: Part[] = value.part === "font" ? ["fontSize", "fontWeight"] : [value.part as Part];
          for (const part of parts) {
            const expected = value.part === "font" ? drawn.parts[part]! : value.value;
            const declared = (ICON_PARTS.has(part) ? icon : box)[CSS_OF[part]];
            compared += 1;
            if (!draws(declared, expected)) missing.push(`${style.variant} ${sample.state} ${part}: page ${expected}, theme ${declared ?? "(none)"} [${selector}]`);
          }
        }
      }
    }
    assert.deepEqual(missing, []);
    assert.ok(compared > 50 || !looks.length, `the comparison ran: ${compared} values`);
  });
}
