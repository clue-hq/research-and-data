import { z } from "zod";

/**
 * F3.2: the cloned-section (fragment) inspector card, frontend shape.
 *
 * A fragment node in a web document pins one immutable harvested artifact and carries flat slot
 * values. Everything ELSE a human needs in order to decide anything about that section — its
 * status, whether the pipeline measured it as broken, its repair lineage, whether the source
 * site hides it and the evidence that said so, and which slots it exposes — lives in the design
 * backend's registry, not in the document. This is that read.
 *
 * Four founder rulings shape it, and each one is why a field is here:
 *
 * * **D-F3 (Option A) + R-A6 amendment (2026-09-04)** — a clone moves as a whole and exposes slot
 *   values AND per-element text overrides; nothing else inside it is editable. `slots` is
 *   therefore the whole editing surface THIS CARD carries: the text overrides are per-instance
 *   values living on the document's fragment node (keyed by structural path), not registry facts
 *   about the harvested artifact, so they are read from the document and never from here. There
 *   is still no field describing the section's internals, because nothing else may edit them.
 * * **D-F6** — the degraded → repaired lineage is visible: `degraded` + what the reason MEANS,
 *   `repairsWhat` on a repair, the whole `family` under any member, and `lineageAmbiguous`
 *   when two released repairs contest the same band.
 * * **D-F8** — a hidden-on-source section is shown as one (`hiddenOnSource`), and activated only
 *   by a human, only with a usable preview: `activation` carries the verdict AND the sentence
 *   the human has to act on.
 * * **P-7** — that preview is an ISOLATION RENDER of the artifact's own harvested bytes, because
 *   a section the site never showed has no screenshot to crop. `previewBasis` keeps the two
 *   kinds of evidence distinguishable rather than letting one pass for the other.
 */

export const FragmentSlotSpecSchema = z.object({
  key: z.string().min(1),
  /** The control this slot takes. `href` and `text` both ride the node's text tag, so this is
   * the only thing that remembers a slot is a link target rather than copy. */
  kind: z.string().min(1),
  fallback: z.union([z.string(), z.boolean(), z.null()]).default(null),
});

export type FragmentSlotSpec = z.infer<typeof FragmentSlotSpecSchema>;

export const FragmentLineageEntrySchema = z.object({
  fragmentId: z.string().min(1),
  label: z.string().nullable().default(null),
  status: z.string().min(1),
  degraded: z.boolean().default(false),
  degradedReason: z.string().nullable().default(null),
  derivedReason: z.string().nullable().default(null),
  previewPath: z.string().nullable().default(null),
  createdAt: z.string().nullable().default(null),
});

export type FragmentLineageEntry = z.infer<typeof FragmentLineageEntrySchema>;

/**
 * One member of the whole lineage — **ruling R18-1**: every repair in a family must be
 * retire-reachable from the card of any family member selectable on the page.
 *
 * A parent/child list cannot deliver that. A repair is on no page unless somebody
 * pinned it, so "select the repair" is not a way to reach one, and a repair-of-a-repair is
 * nobody's direct child except its own parent's — so a grandchild leaf had a retire affordance
 * nowhere at all, and the contested-lineage dead end stayed a dead end with the button built.
 *
 * Membership and the root are the backend resolver's answers (ruling R-X1), never re-derived
 * here. Each entry carries its own `retirement` verdict, so a surface renders a button where one
 * is lawful and a reason where it is not, without knowing R17-3.
 */
export const FragmentFamilyEntrySchema = FragmentLineageEntrySchema.extend({
  derivedFrom: z.string().nullable().default(null),
  isRoot: z.boolean().default(false),
  retirement: z.lazy(() => FragmentVerdictSchema),
});

export type FragmentFamilyEntry = z.infer<typeof FragmentFamilyEntrySchema>;

/** A verdict about an action, with the sentence a human reads when it is `false`. Carrying the
 * message rather than a bare boolean is the point: "no" and "no, and here is the button that
 * fixes it" are different answers. */
export const FragmentVerdictSchema = z.object({
  allowed: z.boolean(),
  reason: z.string().nullable().default(null),
  message: z.string().nullable().default(null),
});

export type FragmentVerdict = z.infer<typeof FragmentVerdictSchema>;

export const FragmentCardSchema = z.object({
  fragmentId: z.string().min(1),
  label: z.string().nullable().default(null),
  sectionRole: z.string().nullable().default(null),
  status: z.string().min(1),
  pageUrl: z.string().nullable().default(null),
  /** Where the band sat in DOCUMENT order. The visible and hidden collections are numbered from
   * one counter, so this is a sort key and NOT an offset into the visible list (F3.0 M3). */
  sectionIndex: z.number().int().nullable().default(null),
  previewPath: z.string().nullable().default(null),
  previewBasis: z.string().nullable().default(null),
  slots: z.array(FragmentSlotSpecSchema).default([]),
  degraded: z.boolean().default(false),
  degradedReason: z.string().nullable().default(null),
  degradedNote: z.string().nullable().default(null),
  derivedFrom: z.string().nullable().default(null),
  derivedReason: z.string().nullable().default(null),
  repairsWhat: FragmentLineageEntrySchema.nullable().default(null),
  supersededBy: z.string().nullable().default(null),
  lineageAmbiguous: z.array(z.string()).default([]),
  lineageRoot: z.string().nullable().default(null),
  family: z.array(FragmentFamilyEntrySchema).default([]),
  hiddenOnSource: z
    .object({
      hidden: z.boolean(),
      evidence: z.array(z.string()).default([]),
    })
    .nullable()
    .default(null),
  activation: FragmentVerdictSchema,
  retirement: FragmentVerdictSchema,
});

export type FragmentCard = z.infer<typeof FragmentCardSchema>;

const FragmentLineageEntryWireSchema = z
  .object({
    fragment_id: z.string().min(1),
    label: z.string().nullish(),
    status: z.string().min(1),
    degraded: z.boolean().optional(),
    degraded_reason: z.string().nullish(),
    derived_reason: z.string().nullish(),
    preview_path: z.string().nullish(),
    created_at: z.string().nullish(),
  })
  .transform((entry) =>
    FragmentLineageEntrySchema.parse({
      fragmentId: entry.fragment_id,
      label: entry.label ?? null,
      status: entry.status,
      degraded: entry.degraded ?? false,
      degradedReason: entry.degraded_reason ?? null,
      derivedReason: entry.derived_reason ?? null,
      previewPath: entry.preview_path ?? null,
      createdAt: entry.created_at ?? null,
    }),
  );

/** The design backend's snake_case card → the frontend shape. */
export const FragmentCardWireSchema = z
  .object({
    fragment_id: z.string().min(1),
    label: z.string().nullish(),
    section_role: z.string().nullish(),
    status: z.string().min(1),
    page_url: z.string().nullish(),
    section_index: z.number().int().nullish(),
    preview: z
      .object({ path: z.string().nullish(), basis: z.string().nullish() })
      .optional(),
    slots: z
      .array(
        z.object({
          key: z.string().min(1),
          kind: z.string().min(1),
          fallback: z.union([z.string(), z.boolean(), z.null()]).optional(),
        }),
      )
      .optional(),
    degraded: z.boolean().optional(),
    degraded_reason: z.string().nullish(),
    degraded_note: z.string().nullish(),
    derived_from: z.string().nullish(),
    derived_reason: z.string().nullish(),
    repairs_what: FragmentLineageEntryWireSchema.nullish(),
    superseded_by: z.string().nullish(),
    lineage_ambiguous: z.array(z.string()).optional(),
    lineage_root: z.string().nullish(),
    family: z
      .array(
        z.object({
          fragment_id: z.string().min(1),
          label: z.string().nullish(),
          status: z.string().min(1),
          degraded: z.boolean().optional(),
          degraded_reason: z.string().nullish(),
          derived_reason: z.string().nullish(),
          preview_path: z.string().nullish(),
          created_at: z.string().nullish(),
          derived_from: z.string().nullish(),
          is_root: z.boolean().optional(),
          retirement: z.object({
            retirable: z.boolean(),
            reason: z.string().nullish(),
            message: z.string().nullish(),
          }),
        }),
      )
      .optional(),
    hidden_on_source: z
      .object({
        hidden: z.boolean(),
        evidence: z.array(z.string()).optional(),
      })
      .nullish(),
    activation: z.object({
      activatable: z.boolean(),
      reason: z.string().nullish(),
      message: z.string().nullish(),
    }),
    retirement: z.object({
      retirable: z.boolean(),
      reason: z.string().nullish(),
      message: z.string().nullish(),
    }),
  })
  .transform((wire) =>
    FragmentCardSchema.parse({
      fragmentId: wire.fragment_id,
      label: wire.label ?? null,
      sectionRole: wire.section_role ?? null,
      status: wire.status,
      pageUrl: wire.page_url ?? null,
      sectionIndex: wire.section_index ?? null,
      previewPath: wire.preview?.path ?? null,
      previewBasis: wire.preview?.basis ?? null,
      slots: (wire.slots ?? []).map((slot) => ({
        key: slot.key,
        kind: slot.kind,
        fallback: slot.fallback ?? null,
      })),
      degraded: wire.degraded ?? false,
      degradedReason: wire.degraded_reason ?? null,
      degradedNote: wire.degraded_note ?? null,
      derivedFrom: wire.derived_from ?? null,
      derivedReason: wire.derived_reason ?? null,
      repairsWhat: wire.repairs_what ?? null,
      supersededBy: wire.superseded_by ?? null,
      lineageAmbiguous: wire.lineage_ambiguous ?? [],
      lineageRoot: wire.lineage_root ?? null,
      family: (wire.family ?? []).map((entry) => ({
        fragmentId: entry.fragment_id,
        label: entry.label ?? null,
        status: entry.status,
        degraded: entry.degraded ?? false,
        degradedReason: entry.degraded_reason ?? null,
        derivedReason: entry.derived_reason ?? null,
        previewPath: entry.preview_path ?? null,
        createdAt: entry.created_at ?? null,
        derivedFrom: entry.derived_from ?? null,
        isRoot: entry.is_root ?? false,
        retirement: {
          allowed: entry.retirement.retirable,
          reason: entry.retirement.reason ?? null,
          message: entry.retirement.message ?? null,
        },
      })),
      hiddenOnSource: wire.hidden_on_source
        ? {
            hidden: wire.hidden_on_source.hidden,
            evidence: wire.hidden_on_source.evidence ?? [],
          }
        : null,
      activation: {
        allowed: wire.activation.activatable,
        reason: wire.activation.reason ?? null,
        message: wire.activation.message ?? null,
      },
      retirement: {
        allowed: wire.retirement.retirable,
        reason: wire.retirement.reason ?? null,
        message: wire.retirement.message ?? null,
      },
    }),
  );

/** The hidden-on-source listing: every section the site does not show (D-F8). */
export const DormantFragmentListWireSchema = z
  .object({ sections: z.array(FragmentCardWireSchema).optional() })
  .transform(({ sections }) => sections ?? []);
