/**
 * The setting-up checklist rows over the NEW onboarding lane's steps (spec 2026-09-12). DATA,
 * deliberately: the derivation (`model/setup-items.ts`) takes the table as a parameter. Labels and
 * detail lines are integration-authored copy pending founder review, as the previous table was.
 */
export interface SetupGroup {
  /** Stable across every poll tick — the frozen SetupRow keys on it. Never renumber. */
  id: string;
  label: string;
  detail: string;
  /** The step kinds this row reports. The FIRST kind decides completion; later kinds only annotate. */
  stepKinds: readonly string[];
}

export const SETUP_GROUPS: readonly SetupGroup[] = [
  {
    id: "company",
    label: "Understanding your company",
    detail: "Positioning, market and competitors",
    stepKinds: ["overview"],
  },
  {
    id: "products",
    label: "Your product lineup",
    detail: "Every offering, from your own pages",
    stepKinds: ["lineup", "catalog_sync"],
  },
  {
    id: "proof",
    label: "Customer proof",
    detail: "Reviews, case studies and named customers",
    stepKinds: ["reviews"],
  },
  {
    id: "audience",
    label: "ICPs and personas",
    detail: "Who you sell to, and who decides",
    stepKinds: ["synthesis", "persona"],
  },
] as const;
