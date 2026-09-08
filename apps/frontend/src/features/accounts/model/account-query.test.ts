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

  assert.deepEqual(sorted.slice(0, 5).map((account) => account.name), [
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
