import { z } from "zod";

/**
 * `BrandBrief@1` on the wire, and its Design.md face.
 *
 * The brief is the per-brand Creative Brief the ingestion brief agent writes
 * beside the kit's tokens (design-brief plan, tier 2). It rides the kit payload
 * as `brand_kit_json.brief`, so the page needs no new endpoint: the brand-kit
 * read this screen already makes carries it.
 *
 * **The markdown is a PROJECTION, never a second source of truth.** Nothing here
 * stores, edits or round-trips prose — `renderBrandBrief` is a pure function of
 * the structured brief, and the structured brief is what the design agent
 * consumes. Editing the rendered document in the panel changes a client-local
 * string, exactly as every other lifted edit on this screen does.
 *
 * The canonical schema is the pydantic `BrandBrief@1`
 * (`subsystems/clue-design/apps/api/lumen_ingestion/brief.py`). This mirror is
 * deliberately tolerant in the same direction the rest of this seam is: the
 * envelope is strict (a `schema_version` this build does not know is NOT a
 * brief), individual rows degrade rather than blanking the document.
 */

const ConfidenceSchema = z.enum(["low", "medium", "high"]).catch("low");

const PaletteScopeSchema = z.enum([
  "canvas",
  "ink",
  "accent-punctuation",
  "tinted-card",
  "statement-surface",
  "motif",
]);

export const BrandBriefSchema = z.object({
  schema_version: z.literal(1),
  characterization: z.object({
    words: z.array(z.string()),
    support: z.string(),
    confidence: ConfidenceSchema,
  }),
  chromatic_moment: z.object({
    element: z.string().nullish(),
    token: z.string().nullish(),
    surrounding: z.string().nullish(),
    quiet: z.boolean().default(false),
    confidence: ConfidenceSchema,
  }),
  signature_compositions: z
    .array(
      z.object({
        name: z.string(),
        structure: z.string(),
        strength: z.enum(["STRONG", "SINGLE"]),
        confidence: ConfidenceSchema,
      }),
    )
    .default([]),
  palette_application: z
    .array(
      z.object({
        token: z.string(),
        scope: PaletteScopeSchema,
        evidence: z.string(),
        confidence: ConfidenceSchema,
      }),
    )
    .default([]),
  background_rhythm: z.object({
    bands: z
      .array(
        z.object({
          index: z.number(),
          token: z.string().nullish(),
          note: z.string().nullish(),
        }),
      )
      .default([]),
    ratio_summary: z.string().nullish(),
    differentiation: z.enum(["chromatic", "compositional"]).nullish(),
    confidence: ConfidenceSchema,
  }),
  typographic_posture: z.object({
    case_posture: z.string().nullish(),
    scale_temperament: z.enum(["restrained", "substantial", "stadium"]).nullish(),
    signature_moves: z.array(z.string()).default([]),
    tokens: z.array(z.string()).default([]),
    confidence: ConfidenceSchema,
  }),
  imagery_posture: z.object({
    diet: z
      .enum(["photography-led", "product-ui-led", "text-forward", "abstract", "absent"])
      .nullish(),
    slots: z.array(z.string()).default([]),
    absences: z.array(z.string()).default([]),
    confidence: ConfidenceSchema,
  }),
  constraints: z
    .array(
      z.object({
        rule: z.string(),
        scope: z.string().nullish(),
        confidence: ConfidenceSchema,
      }),
    )
    .default([]),
  component_recipes: z
    .array(
      z.object({
        component: z.string(),
        variant: z.string(),
        radius: z.string().nullish(),
        padding: z.string().nullish(),
        border: z.string().nullish(),
        shadow: z.string().nullish(),
        background: z.string().nullish(),
        text: z.string().nullish(),
        unmapped: z.array(z.string()).default([]),
        confidence: ConfidenceSchema,
      }),
    )
    .default([]),
  diagnostics: z
    .array(z.object({ observation: z.string(), reason: z.string() }))
    .default([]),
});

export type BrandBrief = z.infer<typeof BrandBriefSchema>;

/**
 * Where the brief lands in the knowledge tree. `design/Design.md` is a file in
 * the section's existing designed slot — a folder and a document, both data.
 */
export const DESIGN_BRIEF_DOCUMENT = {
  documentId: "design-brief",
  folderId: "design",
  folderLabel: "Design",
  name: "Design.md",
  path: "design/Design.md",
} as const;

/**
 * D2, founder-ruled: the brief's RENDERED size is budgeted in TOKENS, and 6,000
 * rendered tokens is the v1 cap (the founder's reference guidance file, ≈25KB,
 * is the size a brief is allowed to be). Past it the render truncates and SAYS
 * SO; the stored structured brief is never truncated.
 */
export const BRAND_BRIEF_TOKEN_BUDGET = 6000;

/** The stated estimator: characters ÷ 4. This seam has no tokenizer, and a
 * pessimistic arithmetic estimate is honest where a fabricated exact count
 * would not be. */
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

export interface BrandBriefRenderMeta {
  brandKitId: string;
  version: number;
  /** The store's own word for the kit's state, already labelled for a reader. */
  approvalLabel: string | null;
  brandName: string;
}

export interface BrandBriefRender {
  markdown: string;
  truncated: boolean;
  /** The headings the budget cut, named so the reader can see what is missing. */
  omitted: string[];
}

interface Section {
  heading: string;
  lines: string[];
}

/**
 * The structured brief as the knowledge panel's markdown.
 *
 * Produces Markdown content; the Knowledge panel delegates rendering to
 * react-markdown with remark-gfm.
 *
 * An empty section is OMITTED, not stubbed: the brief's own law is that absence
 * is a correct answer, and a "Component recipes: none" row would be the first
 * invented sentence on the page.
 */
export function renderBrandBrief(
  brief: BrandBrief,
  meta: BrandBriefRenderMeta,
): BrandBriefRender {
  const header = [
    "# Design.md",
    "",
    `The deployment rules for **${meta.brandName || "this brand"}**, extracted from the brand's own website alongside its kit. This document is a projection of the kit's structured **BrandBrief@1** — the design agent reads the structure, not this prose.`,
    "",
    `- Brand kit: **${meta.brandKitId}** · version ${meta.version}${
      meta.approvalLabel ? ` · ${meta.approvalLabel}` : ""
    }`,
    "",
    "",
  ].join("\n");

  const sections = buildSections(brief);
  const kept: string[] = [];
  const omitted: string[] = [];
  let used = estimateTokens(header);

  for (const section of sections) {
    const text = [`## ${section.heading}`, "", ...section.lines, ""].join("\n");
    const cost = estimateTokens(text);
    // The truncation note has to fit too, so the cap is never exceeded by
    // announcing that it was reached.
    if (omitted.length > 0 || used + cost > BRAND_BRIEF_TOKEN_BUDGET - TRUNCATION_RESERVE) {
      omitted.push(section.heading);
      continue;
    }
    kept.push(text);
    used += cost;
  }

  const markdown =
    omitted.length === 0
      ? `${header}${kept.join("\n")}`
      : `${header}${kept.join("\n")}\n${truncationNote(omitted)}`;

  return { markdown, truncated: omitted.length > 0, omitted };
}

/** Room kept aside for the truncation note itself, in estimated tokens. */
const TRUNCATION_RESERVE = 120;

function truncationNote(omitted: string[]): string {
  return [
    "## This document is truncated",
    "",
    `The rendered brief hit its ${BRAND_BRIEF_TOKEN_BUDGET.toLocaleString("en-US")}-token budget. These sections are in the kit's stored brief but not shown here: ${omitted.join(", ")}.`,
    "",
  ].join("\n");
}

function buildSections(brief: BrandBrief): Section[] {
  const sections: Section[] = [];

  sections.push({
    heading: "Characterization",
    lines: [
      `**${brief.characterization.words.join(", ")}** — ${brief.characterization.support}${confidence(brief.characterization.confidence)}`,
    ],
  });

  const moment = brief.chromatic_moment;
  sections.push({
    heading: "Chromatic moment",
    lines: [
      moment.quiet
        ? `This brand has **no chromatic peak** — the accent stays at punctuation scale everywhere.${confidence(moment.confidence)}`
        : `${moment.element ?? "The saturated moment"}${moment.token ? `, in **${moment.token}**` : ""}${moment.surrounding ? `. ${moment.surrounding}` : ""}${confidence(moment.confidence)}`,
    ],
  });

  pushList(
    sections,
    "Signature compositions",
    brief.signature_compositions.map(
      (entry) =>
        `**${entry.strength}** — ${entry.name}: ${entry.structure}${confidence(entry.confidence)}`,
    ),
  );

  pushList(
    sections,
    "Palette application",
    brief.palette_application.map(
      (entry) =>
        `**${entry.token}** — ${entry.scope}: ${entry.evidence}${confidence(entry.confidence)}`,
    ),
  );

  const rhythm = brief.background_rhythm;
  const rhythmLines: string[] = [];
  if (rhythm.ratio_summary || rhythm.differentiation) {
    rhythmLines.push(
      [
        rhythm.ratio_summary,
        rhythm.differentiation
          ? `Differentiation is ${rhythm.differentiation}.`
          : null,
      ]
        .filter(Boolean)
        .join(". ") + confidence(rhythm.confidence),
    );
    rhythmLines.push("");
  }
  for (const band of rhythm.bands) {
    // A bullet, not `1.` — the knowledge panel's markdown grammar knows `- `
    // and nothing else, so a numbered line renders as one run-on paragraph.
    rhythmLines.push(
      `- Band ${band.index + 1}: **${band.token ?? "no kit token"}**${band.note ? ` — ${band.note}` : ""}`,
    );
  }
  if (rhythmLines.length > 0) {
    sections.push({ heading: "Background rhythm", lines: rhythmLines });
  }

  const type = brief.typographic_posture;
  const typeLines = [
    type.case_posture ? `Case: ${type.case_posture}` : null,
    type.scale_temperament ? `Scale: ${type.scale_temperament}` : null,
    type.tokens.length ? `Tokens: ${type.tokens.map(bold).join(", ")}` : null,
    ...type.signature_moves,
  ].filter((line): line is string => Boolean(line));
  pushList(sections, "Typographic posture", typeLines);

  const imagery = brief.imagery_posture;
  const imageryLines = [
    imagery.diet ? `Diet: ${imagery.diet}` : null,
    ...imagery.slots,
    ...imagery.absences.map((absence) => `**Absent** — ${absence}`),
  ].filter((line): line is string => Boolean(line));
  pushList(sections, "Imagery posture", imageryLines);

  pushList(
    sections,
    "Constraints",
    brief.constraints.map(
      (entry) =>
        `${entry.rule}${entry.scope ? ` (${entry.scope})` : ""}${confidence(entry.confidence)}`,
    ),
  );

  pushList(
    sections,
    "Component recipes",
    brief.component_recipes.map((recipe) => {
      const slots = (
        [
          ["radius", recipe.radius],
          ["padding", recipe.padding],
          ["border", recipe.border],
          ["shadow", recipe.shadow],
          ["background", recipe.background],
          ["text", recipe.text],
        ] as const
      )
        .filter(([, token]) => Boolean(token))
        .map(([slot, token]) => `${slot} ${bold(token as string)}`)
        .join(", ");
      const unmapped = recipe.unmapped.length
        ? ` — untokenized: ${recipe.unmapped.join("; ")}`
        : "";
      return `**${recipe.component} / ${recipe.variant}** — ${slots || "no tokenized slots"}${unmapped}${confidence(recipe.confidence)}`;
    }),
  );

  pushList(
    sections,
    "Observations with no token",
    brief.diagnostics.map((entry) => `${entry.observation} — ${entry.reason}`),
  );

  return sections;
}

function pushList(sections: Section[], heading: string, items: string[]): void {
  if (items.length === 0) return;
  sections.push({ heading, lines: items.map((item) => `- ${item}`) });
}

function bold(value: string): string {
  return `**${value}**`;
}

function confidence(level: BrandBrief["characterization"]["confidence"]): string {
  return ` (${level} confidence)`;
}
