import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  BRAND_BRIEF_TOKEN_BUDGET,
  BrandBriefSchema,
  DESIGN_BRIEF_DOCUMENT,
  estimateTokens,
  renderBrandBrief,
  type BrandBrief,
} from "./brand-brief";

const BRIEF: BrandBrief = BrandBriefSchema.parse({
  schema_version: 1,
  characterization: {
    words: ["expansive", "polished", "technical"],
    support: "Stadium-scale light headlines on white, violet CTAs as the only hard fill.",
    confidence: "high",
  },
  chromatic_moment: {
    element: "the primary filled CTA",
    token: "surface.brand",
    surrounding: "white canvas, text.inverse label",
    quiet: false,
    confidence: "high",
  },
  signature_compositions: [
    {
      name: "stat band",
      structure: "oversized numerals across a dark full-bleed band",
      strength: "STRONG",
      confidence: "high",
    },
  ],
  palette_application: [
    {
      token: "surface.brand",
      scope: "accent-punctuation",
      evidence: "CTA fills only",
      confidence: "high",
    },
  ],
  background_rhythm: {
    bands: [
      { index: 0, token: "surface.page", note: "hero" },
      { index: 1, token: null, note: "navy statement band — no kit token" },
    ],
    ratio_summary: "6 white bands : 2 navy slivers",
    differentiation: "chromatic",
    confidence: "high",
  },
  typographic_posture: {
    case_posture: "sentence case",
    scale_temperament: "stadium",
    signature_moves: ["tracked uppercase eyebrow"],
    tokens: ["type.display", "type.body"],
    confidence: "high",
  },
  imagery_posture: {
    diet: "product-ui-led",
    slots: ["hero right"],
    absences: ["no photography in pricing"],
    confidence: "medium",
  },
  constraints: [
    {
      rule: "surface.brand is the sole saturated fill",
      scope: "buttons",
      confidence: "high",
    },
  ],
  component_recipes: [
    {
      component: "button",
      variant: "primary",
      radius: "radius.button",
      padding: "space.md",
      border: null,
      shadow: null,
      background: "surface.brand",
      text: "text.inverse",
      unmapped: ["padding measured ~12px × 20px"],
      confidence: "high",
    },
  ],
  diagnostics: [
    {
      observation: "a navy statement band at ~#0D1738",
      reason: "no kit surface token carries that value",
    },
  ],
});

const META = {
  brandKitId: "brand_kit_ing_abc",
  version: 3,
  approvalLabel: "Approved",
  brandName: "Stripe",
};

test("the document is named for the designed knowledge slot", () => {
  assert.equal(DESIGN_BRIEF_DOCUMENT.path, "design/Design.md");
  assert.equal(DESIGN_BRIEF_DOCUMENT.name, "Design.md");
  assert.equal(DESIGN_BRIEF_DOCUMENT.folderId, "design");
});

test("the rendered header names the kit, its version and its approval state", () => {
  const { markdown } = renderBrandBrief(BRIEF, META);
  const header = markdown.slice(0, markdown.indexOf("## "));
  assert.match(header, /brand_kit_ing_abc/);
  assert.match(header, /version 3/);
  assert.match(header, /Approved/);
  assert.match(header, /BrandBrief@1/);
});

test("every section of the structured brief reaches the projection", () => {
  const { markdown, truncated } = renderBrandBrief(BRIEF, META);
  assert.equal(truncated, false);
  for (const heading of [
    "## Characterization",
    "## Chromatic moment",
    "## Signature compositions",
    "## Palette application",
    "## Background rhythm",
    "## Typographic posture",
    "## Imagery posture",
    "## Constraints",
    "## Component recipes",
    "## Observations with no token",
  ]) {
    assert.ok(markdown.includes(heading), `missing ${heading}`);
  }
  assert.match(markdown, /expansive, polished, technical/);
  assert.match(markdown, /surface\.brand/);
  assert.match(markdown, /STRONG/);
  assert.match(markdown, /radius\.button/);
  assert.match(markdown, /no kit surface token carries that value/);
});

test("a band with no token says so rather than dropping out of the rhythm", () => {
  const { markdown } = renderBrandBrief(BRIEF, META);
  assert.match(markdown, /no kit token/);
});

test("every band is a list item the panel can render", () => {
  const { markdown } = renderBrandBrief(BRIEF, META);
  const rhythm = markdown.slice(
    markdown.indexOf("## Background rhythm"),
    markdown.indexOf("## Typographic posture"),
  );
  const html = renderToStaticMarkup(createElement(Markdown, { remarkPlugins: [remarkGfm] }, rhythm));
  assert.equal((html.match(/<li>/g) ?? []).length, 2);
});

test("a quiet brand's chromatic moment reads as a rule, not as an absence", () => {
  const quiet = BrandBriefSchema.parse({
    ...BRIEF,
    chromatic_moment: {
      element: null,
      token: null,
      surrounding: null,
      quiet: true,
      confidence: "low",
    },
  });
  const { markdown } = renderBrandBrief(quiet, META);
  assert.match(markdown, /no chromatic peak/i);
});

test("the projection parses as the knowledge panel's markdown", () => {
  const { markdown } = renderBrandBrief(BRIEF, META);
  const html = renderToStaticMarkup(createElement(Markdown, { remarkPlugins: [remarkGfm] }, markdown));
  assert.match(html, /<h1>Design\.md<\/h1>/);
  assert.match(html, /<ul>/);
  assert.match(html, /<strong>/);
});

test("the render is capped, and a truncated render says so", () => {
  const wordy = BrandBriefSchema.parse({
    ...BRIEF,
    constraints: Array.from({ length: 40 }, (_, index) => ({
      rule: `${"rule ".repeat(120)}#${index}`,
      scope: "everywhere",
      confidence: "high",
    })),
  });
  const { markdown, truncated, omitted } = renderBrandBrief(wordy, META);
  assert.equal(truncated, true);
  assert.ok(
    estimateTokens(markdown) <= BRAND_BRIEF_TOKEN_BUDGET,
    `render estimated ${estimateTokens(markdown)} tokens`,
  );
  // Honest, and specific about what the reader is not seeing.
  assert.match(markdown, /truncated/i);
  assert.ok(omitted.length > 0);
  assert.match(markdown, new RegExp(omitted[0]));
});

test("truncation never touches the structured brief", () => {
  const before = JSON.stringify(BRIEF);
  renderBrandBrief(BRIEF, META);
  assert.equal(JSON.stringify(BRIEF), before);
});

test("the budget is the ruled 6,000 rendered tokens", () => {
  assert.equal(BRAND_BRIEF_TOKEN_BUDGET, 6000);
  // chars/4, the stated estimator — no token library on this seam.
  assert.equal(estimateTokens("12345678"), 2);
});

test("an unrecognized brief shape is not a brief", () => {
  assert.equal(BrandBriefSchema.safeParse({ schema_version: 2 }).success, false);
  assert.equal(BrandBriefSchema.safeParse(null).success, false);
});

test("a brief with every list empty still renders its anchor", () => {
  const bare = BrandBriefSchema.parse({
    schema_version: 1,
    characterization: {
      words: ["quiet", "editorial"],
      support: "One page of evidence.",
      confidence: "low",
    },
    chromatic_moment: { quiet: true, confidence: "low" },
    signature_compositions: [],
    palette_application: [],
    background_rhythm: { bands: [], confidence: "low" },
    typographic_posture: { signature_moves: [], tokens: [], confidence: "low" },
    imagery_posture: { slots: [], absences: [], confidence: "low" },
    constraints: [],
    component_recipes: [],
    diagnostics: [],
  });
  const { markdown } = renderBrandBrief(bare, META);
  assert.match(markdown, /quiet, editorial/);
  // An empty section is simply absent — no invented placeholder rows.
  assert.equal(markdown.includes("## Component recipes"), false);
  assert.equal(markdown.includes("## Observations with no token"), false);
});
