export type AccountColumnKey =
  | "company"
  | "research"
  | "fit"
  | "score"
  | "revenue"
  | "size"
  | "locations";

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
  "fit",
  "score",
  "revenue",
  "size",
  "locations",
];

export const defaultAccountColumns: Record<AccountColumnKey, boolean> = {
  company: true,
  research: true,
  fit: true,
  score: true,
  revenue: true,
  size: true,
  locations: true,
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
  research: 160,
  fit: 140,
  score: 140,
  revenue: 140,
  size: 140,
  locations: 140,
};

export const accountColumnWidthConstraints: Record<
  AccountColumnKey,
  { max: number; min: number }
> = {
  company: { max: 640, min: 180 },
  research: { max: 480, min: 136 },
  fit: { max: 400, min: 120 },
  score: { max: 400, min: 120 },
  revenue: { max: 480, min: 120 },
  size: { max: 400, min: 112 },
  locations: { max: 400, min: 112 },
};
