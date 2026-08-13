import assert from "node:assert/strict";
import test from "node:test";
import type { Account, AccountProject } from "./account";
import { filterAccounts, sortAccounts } from "./account-query";

const revenueProject: AccountProject = {
  projectId: "revenue",
  name: "10x revenue",
  addedVia: "directive",
  addedAt: "2026-08-01T00:00:00Z",
};
const conferenceProject: AccountProject = {
  projectId: "conference",
  name: "Conference",
  addedVia: "discovered",
  addedAt: "2026-08-02T00:00:00Z",
};
const reportsProject: AccountProject = {
  projectId: "reports",
  name: "Custom reports",
  addedVia: "imported",
  addedAt: "2026-08-03T00:00:00Z",
};

function account(
  id: string,
  name: string,
  options: Partial<Account> = {},
): Account {
  return {
    id,
    name,
    domain: null,
    employeeCount: null,
    revenueBand: null,
    logoUrl: null,
    projects: [],
    primaryProjectId: null,
    scores: [],
    researchStatus: [],
    updatedAt: null,
    ...options,
  };
}

const accounts: Account[] = [
  account("neuralink", "Neuralink"),
  account("anthropic", "Anthropic", {
    employeeCount: 1100,
    projects: [revenueProject],
    primaryProjectId: revenueProject.projectId,
    scores: [
      {
        projectId: revenueProject.projectId,
        fit: 0.78,
        intent: 0.4,
        icpKey: "enterprise-ai",
        icpVersion: 1,
        scoredAt: "2026-08-01T00:00:00Z",
      },
    ],
  }),
  account("openai", "OpenAI", {
    employeeCount: 3200,
    projects: [revenueProject, conferenceProject],
    primaryProjectId: revenueProject.projectId,
    scores: [
      {
        projectId: revenueProject.projectId,
        fit: 0.81,
        intent: null,
        icpKey: "enterprise-ai",
        icpVersion: 2,
        scoredAt: "2026-08-01T00:00:00Z",
      },
    ],
    researchStatus: [
      { projectId: revenueProject.projectId, status: "needs_review" },
    ],
  }),
  account("airtable", "Airtable", {
    projects: [conferenceProject],
    primaryProjectId: conferenceProject.projectId,
    researchStatus: [
      { projectId: conferenceProject.projectId, status: "needs_review" },
    ],
  }),
  account("snowflake", "Snowflake", {
    projects: [conferenceProject],
    primaryProjectId: conferenceProject.projectId,
  }),
  account("perplexity", "Perplexity AI", {
    projects: [reportsProject],
    primaryProjectId: reportsProject.projectId,
  }),
];

test("project filters match every project associated with an account", () => {
  const filtered = filterAccounts(accounts, [
    {
      field: "project",
      id: "project-filter",
      join: "and",
      operator: "is",
      value: "conference",
    },
  ]);

  assert.deepEqual(
    filtered.map((item) => item.id),
    ["openai", "airtable", "snowflake"],
  );
});

test("project sort uses the primary project and account name as a stable tie-breaker", () => {
  const sorted = sortAccounts(accounts, "project-asc");

  assert.equal(sorted[0]?.id, "neuralink");
  assert.deepEqual(
    sorted.slice(1, 3).map((item) => item.id),
    ["anthropic", "openai"],
  );
});

test("filters preserve the authored and-or sequence", () => {
  const filtered = filterAccounts(accounts, [
    {
      field: "project",
      id: "project-filter",
      join: "and",
      operator: "is",
      value: "revenue",
    },
    {
      field: "name",
      id: "name-filter",
      join: "and",
      operator: "contains",
      value: "open",
    },
  ]);

  assert.deepEqual(filtered.map((item) => item.id), ["openai"]);
});

test("research status filters against every project status", () => {
  const filtered = filterAccounts(accounts, [
    {
      field: "researchStatus",
      id: "status-filter",
      join: "and",
      operator: "is",
      value: "needs_review",
    },
  ]);

  assert.deepEqual(filtered.map((item) => item.id), ["openai", "airtable"]);
});

test("a numeric filter over per-project scores matches any scored project", () => {
  const filtered = filterAccounts(accounts, [
    {
      field: "fitScore",
      id: "score-filter",
      join: "and",
      operator: "greater-than",
      value: "75",
    },
  ]);

  assert.deepEqual(filtered.map((item) => item.id), ["anthropic", "openai"]);
});

test("an account with no value for the filtered field never matches it", () => {
  const filtered = filterAccounts(accounts, [
    {
      field: "employeeCount",
      id: "size-filter",
      join: "and",
      operator: "greater-than",
      value: "0",
    },
  ]);

  assert.equal(filtered.some((item) => item.id === "neuralink"), false);
});
