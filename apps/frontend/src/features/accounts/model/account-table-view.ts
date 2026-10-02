import type { Account } from "./account";

export type CoreAccountColumnKey =
  | "company"
  | "owner"
  | "industry"
  | "research"
  | "fit"
  | "score"
  | "revenue"
  | "headcount"
  | "locations"
  | "website"
  | "linkedin"
  | "twitter"
  | "facebook"
  | "instagram"
  | "created"
  | "modified";
export type AccountVariableColumnKey = `variable:${string}`;
export type AccountColumnKey =
  | CoreAccountColumnKey
  | AccountVariableColumnKey;

export interface AccountColumnDefinition {
  icon: string;
  key: AccountColumnKey;
  kind: "core" | "variable";
  label: string;
  maxWidth: number;
  minWidth: number;
  variableId?: string;
  width: number;
}

export type AccountSort =
  | "default"
  | "name-asc"
  | "name-desc"
  | "project-asc"
  | "project-desc";
export type AccountTableDensity = "compact" | "comfortable" | "spacious";
export type AccountColumnWidths = Record<string, number>;
export type AccountColumnVisibility = Record<string, boolean>;

export const coreAccountColumnDefinitions: AccountColumnDefinition[] = [
  {
    icon: "account",
    key: "company",
    kind: "core",
    label: "Company name",
    maxWidth: 640,
    minWidth: 180,
    width: 280,
  },
  {
    icon: "owner",
    key: "owner",
    kind: "core",
    label: "Owner",
    maxWidth: 480,
    minWidth: 150,
    width: 180,
  },
  {
    icon: "industry",
    key: "industry",
    kind: "core",
    label: "Industry",
    maxWidth: 560,
    minWidth: 180,
    width: 260,
  },
  {
    icon: "research-status",
    key: "research",
    kind: "core",
    label: "Research status",
    maxWidth: 480,
    minWidth: 136,
    width: 160,
  },
  {
    icon: "overall-fit",
    key: "fit",
    kind: "core",
    label: "Overall fit",
    maxWidth: 400,
    minWidth: 120,
    width: 140,
  },
  {
    icon: "fit-score",
    key: "score",
    kind: "core",
    label: "Fit score",
    maxWidth: 400,
    minWidth: 120,
    width: 140,
  },
  {
    icon: "revenue",
    key: "revenue",
    kind: "core",
    label: "Revenue",
    maxWidth: 480,
    minWidth: 120,
    width: 140,
  },
  {
    icon: "headcount",
    key: "headcount",
    kind: "core",
    label: "Headcount",
    maxWidth: 400,
    minWidth: 112,
    width: 140,
  },
  {
    icon: "locations",
    key: "locations",
    kind: "core",
    label: "Locations",
    maxWidth: 400,
    minWidth: 112,
    width: 140,
  },
  {
    icon: "website",
    key: "website",
    kind: "core",
    label: "Website",
    maxWidth: 520,
    minWidth: 180,
    width: 220,
  },
  ...(["LinkedIn", "Twitter", "Facebook", "Instagram"] as const).map(
    (label): AccountColumnDefinition => ({
      icon: "social",
      key: label.toLowerCase() as
        | "linkedin"
        | "twitter"
        | "facebook"
        | "instagram",
      kind: "core",
      label,
      maxWidth: 440,
      minWidth: 130,
      width: 150,
    }),
  ),
  {
    icon: "created",
    key: "created",
    kind: "core",
    label: "Date Created",
    maxWidth: 420,
    minWidth: 140,
    width: 160,
  },
  {
    icon: "modified",
    key: "modified",
    kind: "core",
    label: "Last Modified",
    maxWidth: 420,
    minWidth: 140,
    width: 160,
  },
];

export const defaultAccountColumnOrder = coreAccountColumnDefinitions.map(
  (column) => column.key,
);

export const defaultAccountColumns = Object.fromEntries(
  coreAccountColumnDefinitions.map((column) => [column.key, true]),
) as AccountColumnVisibility;

export function createAccountColumnDefinitions(accounts: Account[]) {
  const variables = new Map<
    string,
    Account["customFields"][number]
  >();

  for (const account of accounts) {
    for (const variable of account.customFields) {
      if (!variables.has(variable.id)) variables.set(variable.id, variable);
    }
  }

  return [
    ...coreAccountColumnDefinitions,
    ...[...variables.values()].map(
      (variable): AccountColumnDefinition => ({
        icon: "variable",
        key: `variable:${variable.id}`,
        kind: "variable",
        label: variable.label,
        maxWidth: 480,
        minWidth: 120,
        variableId: variable.id,
        width: 140,
      }),
    ),
  ];
}

export function createAccountColumnOrder(
  definitions: AccountColumnDefinition[],
) {
  return definitions.map((column) => column.key);
}

export function createAccountColumnVisibility(
  definitions: AccountColumnDefinition[],
) {
  return Object.fromEntries(
    definitions.map((column) => [column.key, true]),
  ) as AccountColumnVisibility;
}

export function createAccountColumnWidths(
  definitions: AccountColumnDefinition[],
) {
  return Object.fromEntries(
    definitions.map((column) => [column.key, column.width]),
  ) as AccountColumnWidths;
}

export function getFirstScrollableAccountColumn(
  visibleColumns: AccountColumnVisibility,
  columnOrder: AccountColumnKey[],
) {
  return columnOrder.find(
    (column) => column !== "company" && visibleColumns[column],
  );
}

export const defaultAccountColumnWidths = createAccountColumnWidths(
  coreAccountColumnDefinitions,
);
