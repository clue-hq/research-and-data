import { z } from "zod";
import type { Account } from "./account";
import type { AccountSort } from "./account-table-view";

/**
 * The authored filter shell.
 *
 * These rules run client-side over the loaded page. The slice-1 read layer
 * serves no `search`, `sort`, or query-POST endpoint, so nothing here is sent
 * to the backend; the only wire filter is `projectId`.
 *
 * The field set follows the as-built wire: `overallFit` is gone (it was never a
 * backend concept and D-6 refuses to invent it), `employeeBand` became the
 * integer `employeeCount`, and `locationCount` is dropped with the rest of the
 * fixture-only fields (D-7).
 */
export const AccountFilterFieldSchema = z.enum([
  "name",
  "project",
  "researchStatus",
  "fitScore",
  "revenueBand",
  "employeeCount",
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

export function isNumericAccountFilterField(field: AccountFilterField) {
  return field === "fitScore" || field === "employeeCount";
}

export function defaultAccountFilterOperator(
  field: AccountFilterField,
): AccountFilterOperator {
  if (isNumericAccountFilterField(field)) {
    return "greater-than";
  }

  if (
    field === "project" ||
    field === "researchStatus" ||
    field === "revenueBand"
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

function normalized(value: string | number) {
  return String(value).trim().toLocaleLowerCase();
}

/**
 * The project a project-sort orders by.
 *
 * Falls back to the first membership when `primaryProjectId` names none, and
 * to the empty string when the project has no resolvable name — an unnamed
 * project sorts first rather than sorting by a raw id the user never sees.
 */
export function primaryProjectName(account: Account) {
  return (
    account.projects.find(
      (project) => project.projectId === account.primaryProjectId,
    )?.name ??
    account.projects[0]?.name ??
    ""
  );
}

function accountFieldValues(
  account: Account,
  field: AccountFilterField,
): Array<string | number> {
  switch (field) {
    case "name":
      return [account.name];
    case "project":
      return account.projects.flatMap((project) =>
        project.name === null
          ? [project.projectId]
          : [project.projectId, project.name],
      );
    case "researchStatus":
      return account.researchStatus.map((entry) => entry.status);
    case "fitScore":
      // Compared on the 0-100 scale the table renders, not the 0-1 wire value.
      return account.scores.flatMap((score) =>
        score.fit === null ? [] : [Math.round(score.fit * 100)],
      );
    case "revenueBand":
      return account.revenueBand === null ? [] : [account.revenueBand];
    case "employeeCount":
      return account.employeeCount === null ? [] : [account.employeeCount];
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

export function filterAccounts(
  accounts: Account[],
  rules: AccountFilterRule[],
) {
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

/**
 * Sorts the loaded page.
 *
 * Two accounts can legitimately share a name (the same clinic group in two
 * regions), so a name sort tie-breaks on the primary project id and then on the
 * account id — a total order, so the row sequence never shuffles between
 * renders of the same data.
 */
export function sortAccounts(accounts: Account[], sort: AccountSort) {
  if (sort === "default") return accounts;

  return [...accounts].sort((first, second) => {
    const descending = sort.endsWith("-desc");
    const tieBreak =
      (first.primaryProjectId ?? "").localeCompare(
        second.primaryProjectId ?? "",
      ) || first.id.localeCompare(second.id);
    const comparison = sort.startsWith("project")
      ? primaryProjectName(first).localeCompare(primaryProjectName(second)) ||
        first.name.localeCompare(second.name) ||
        tieBreak
      : first.name.localeCompare(second.name) || tieBreak;

    return descending ? -comparison : comparison;
  });
}
