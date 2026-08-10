/**
 * Accounts-table view configuration (presentation only — no wire meaning).
 *
 * The column set tracks the as-built list row: the fixture-era `fit`
 * (`overallFit`, never a backend concept — D-6) and `locations`
 * (`locationCount`, an industry-pack placeholder — D-7) columns are gone;
 * `projects` replaces them, because project membership now carries a resolved
 * name and is the axis the table filters and sorts on.
 */
export type AccountColumnKey =
  | "company"
  | "research"
  | "score"
  | "revenue"
  | "size"
  | "projects";

export type AccountSort =
  | "default"
  | "name-asc"
  | "name-desc"
  | "project-asc"
  | "project-desc";
export type AccountTableDensity = "compact" | "comfortable" | "spacious";
export type AccountColumnWidths = Record<AccountColumnKey, number>;

export const defaultAccountColumnOrder: AccountColumnKey[] = [
  "company",
  "research",
  "score",
  "revenue",
  "size",
  "projects",
];

export const defaultAccountColumns: Record<AccountColumnKey, boolean> = {
  company: true,
  research: true,
  score: true,
  revenue: true,
  size: true,
  projects: true,
};

export function getFirstScrollableAccountColumn(
  visibleColumns: Record<AccountColumnKey, boolean>,
  columnOrder: AccountColumnKey[],
) {
  return columnOrder.find(
    (column) => column !== "company" && visibleColumns[column],
  );
}

export const defaultAccountColumnWidths: AccountColumnWidths = {
  company: 280,
  research: 180,
  score: 140,
  revenue: 160,
  size: 140,
  projects: 220,
};

export const accountColumnWidthConstraints: Record<
  AccountColumnKey,
  { max: number; min: number }
> = {
  company: { max: 640, min: 180 },
  research: { max: 480, min: 136 },
  score: { max: 400, min: 120 },
  revenue: { max: 480, min: 120 },
  size: { max: 400, min: 112 },
  projects: { max: 520, min: 140 },
};
