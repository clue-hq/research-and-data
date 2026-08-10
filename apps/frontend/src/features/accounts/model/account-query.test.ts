import assert from "node:assert/strict";
import test from "node:test";
import { accountFixtures } from "../data/accounts.fixture";
import { filterAccounts, sortAccounts } from "./account-query";

test("project filters match every project associated with an account", () => {
  const filtered = filterAccounts(accountFixtures, [
    {
      field: "project",
      id: "project-filter",
      join: "and",
      operator: "is",
      value: "conference-2026",
    },
  ]);

  assert.deepEqual(
    filtered.map((account) => account.id),
    ["openai", "hugging-face", "airtable", "snowflake", "cursor"],
  );
});

test("project sort uses the primary project and account name as a stable tie-breaker", () => {
  const sorted = sortAccounts(accountFixtures, "project-asc");

  // Neuralink has no membership at all, so it has no project name to sort by
  // and leads the ascending order rather than being hidden.
  assert.deepEqual(sorted.slice(0, 6).map((account) => account.name), [
    "Neuralink",
    "Anthropic",
    "Cohere",
    "Google DeepMind",
    "OpenAI",
    "Scale AI",
  ]);
  assert.deepEqual(sorted.slice(-3).map((account) => account.name), [
    "Midjourney",
    "Mistral AI",
    "Perplexity AI",
  ]);
});

test("filters preserve the authored and-or sequence", () => {
  const filtered = filterAccounts(accountFixtures, [
    {
      field: "project",
      id: "project-filter",
      join: "and",
      operator: "is",
      value: "10m-landing-page-campaign",
    },
    {
      field: "name",
      id: "name-filter",
      join: "and",
      operator: "contains",
      value: "open",
    },
  ]);

  assert.deepEqual(filtered.map((account) => account.id), ["openai"]);
});

test("research status filters against the backend vocabulary, across every project", () => {
  const filtered = filterAccounts(accountFixtures, [
    {
      field: "researchStatus",
      id: "status-filter",
      join: "and",
      operator: "is",
      value: "needs_review",
    },
  ]);

  assert.deepEqual(filtered.map((account) => account.id), ["openai", "airtable"]);
});

test("a numeric filter over per-project scores matches on any scored project", () => {
  const filtered = filterAccounts(accountFixtures, [
    {
      field: "fitScore",
      id: "score-filter",
      join: "and",
      operator: "greater-than",
      value: "75",
    },
  ]);

  assert.deepEqual(filtered.map((account) => account.id), [
    "anthropic",
    "openai",
  ]);
});

test("an account with no value for the filtered field never matches it", () => {
  const filtered = filterAccounts(accountFixtures, [
    {
      field: "employeeCount",
      id: "size-filter",
      join: "and",
      operator: "greater-than",
      value: "0",
    },
  ]);

  assert.equal(
    filtered.some((account) => account.id === "neuralink"),
    false,
  );
});
