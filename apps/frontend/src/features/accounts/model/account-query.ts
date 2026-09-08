import { z } from "zod";
import type { Account } from "./account";
import type { AccountSort } from "./account-table-view";

export const AccountFilterFieldSchema = z.enum([
  "name",
  "project",
  "researchStatus",
  "overallFit",
  "fitScore",
  "revenueBand",
  "employeeBand",
  "locationCount",
]);

export const AccountFilterOperatorSchema = z.enum([
  "contains",
  "is",
  "does-not-contain",
  "is-not",
  "greater-than",
  "less-than",
]);

export const AccountFilterJoinSchema = z.enum(["and", "or"]);

export const AccountFilterRuleSchema = z.object({
  field: AccountFilterFieldSchema,
  id: z.string().min(1),
  join: AccountFilterJoinSchema,
  operator: AccountFilterOperatorSchema,
  value: z.string(),
});

export type AccountFilterField = z.infer<typeof AccountFilterFieldSchema>;
export type AccountFilterJoin = z.infer<typeof AccountFilterJoinSchema>;
export type AccountFilterOperator = z.infer<
  typeof AccountFilterOperatorSchema
>;
export type AccountFilterRule = z.infer<typeof AccountFilterRuleSchema>;

export function defaultAccountFilterOperator(
  field: AccountFilterField,
): AccountFilterOperator {
  if (field === "fitScore" || field === "locationCount") {
    return "greater-than";
  }

  if (
    field === "project" ||
    field === "researchStatus" ||
    field === "overallFit" ||
    field === "revenueBand" ||
    field === "employeeBand"
  ) {
    return "is";
  }

  return "contains";
}

export function createDefaultAccountFilterRules(): AccountFilterRule[] {
  return [
    {
      field: "name",
      id: "account-filter-1",
      join: "and",
      operator: "contains",
      value: "",
    },
  ];
}

function normalized(value: string | number | null) {
  if (value === null) return "";
  return String(value).trim().toLocaleLowerCase();
}

function primaryProjectName(account: Account) {
  return (
    account.projects.find(
      (project) => project.id === account.primaryProjectId,
    )?.name ?? account.projects[0]?.name ?? ""
  );
}

function accountFieldValues(account: Account, field: AccountFilterField) {
  switch (field) {
    case "name":
      return [account.name];
    case "project":
      return account.projects.flatMap((project) => [project.id, project.name]);
    case "researchStatus":
      return [account.researchStatus];
    case "overallFit":
      return [account.overallFit];
    case "fitScore":
      return [account.fitScore];
    case "revenueBand":
      return [account.revenueBand];
    case "employeeBand":
      return [account.employeeBand];
    case "locationCount":
      return [account.locationCount];
  }
}

function accountMatchesRule(account: Account, rule: AccountFilterRule) {
  const target = normalized(rule.value);
  if (!target) return true;

  const values = accountFieldValues(account, rule.field);
  const numericTarget = Number(rule.value);

  if (rule.operator === "greater-than" || rule.operator === "less-than") {
    if (!Number.isFinite(numericTarget)) return true;
    return values.some((value) => {
      if (value === null) return false;
      const numericValue = Number(value);
      return rule.operator === "greater-than"
        ? numericValue > numericTarget
        : numericValue < numericTarget;
    });
  }

  const normalizedValues = values.map(normalized);
  if (rule.operator === "contains") {
    return normalizedValues.some((value) => value.includes(target));
  }
  if (rule.operator === "does-not-contain") {
    return normalizedValues.every((value) => !value.includes(target));
  }
  if (rule.operator === "is-not") {
    return normalizedValues.every((value) => value !== target);
  }
  return normalizedValues.some((value) => value === target);
}

// Generic in the row type so a locally created draft keeps its UI-only marker
// through the filter and the sort (`AccountRow`, model/create-account.ts).
export function filterAccounts<T extends Account>(
  accounts: T[],
  rules: AccountFilterRule[],
): T[] {
  const activeRules = rules.filter((rule) => rule.value.trim());
  if (!activeRules.length) return accounts;

  return accounts.filter((account) => {
    let matches = accountMatchesRule(account, activeRules[0]);
    for (const rule of activeRules.slice(1)) {
      const ruleMatches = accountMatchesRule(account, rule);
      matches = rule.join === "or" ? matches || ruleMatches : matches && ruleMatches;
    }
    return matches;
  });
}

export function sortAccounts<T extends Account>(
  accounts: T[],
  sort: AccountSort,
): T[] {
  if (sort === "default") return accounts;

  return [...accounts].sort((first, second) => {
    const descending = sort.endsWith("-desc");
    const comparison = sort.startsWith("project")
      ? primaryProjectName(first).localeCompare(primaryProjectName(second)) ||
        first.name.localeCompare(second.name)
      : first.name.localeCompare(second.name);

    return descending ? -comparison : comparison;
  });
}
