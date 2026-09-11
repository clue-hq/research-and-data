import assert from "node:assert/strict";
import test from "node:test";
import { accountFixtures } from "../data/accounts.fixture";
import { DISABLED_ACCOUNT_BULK_CAPABILITIES } from "../data/bulk-capabilities.repository";
import { workspaceProfileFixture } from "../data/workspace-profile.fixture";
import {
  ProjectAccountsResponseSchema,
  WorkspaceProfileSchema,
  accountsForProject,
  paginateAccounts,
} from "./project-accounts";
import { workspaceProfileForUserId } from "./workspace-profile";
import { filterAccounts, sortAccounts } from "./account-query";

test("membership includes secondary projects and never falls back to the global directory", () => {
  const conference = accountsForProject(accountFixtures, "conference-2026");
  assert.ok(conference.some(({ id }) => id === "openai"));
  assert.ok(conference.every((account) => account.projects.some(({ id }) => id === "conference-2026")));
  assert.deepEqual(accountsForProject(accountFixtures, "empty-project"), []);
});

test("an OR filter cannot bring another project's accounts into the table", () => {
  const scoped = accountsForProject(accountFixtures, "custom-reports");
  const results = filterAccounts(scoped, [
    { id: "1", field: "name", operator: "contains", join: "and", value: "Cursor" },
    { id: "2", field: "name", operator: "contains", join: "or", value: "OpenAI" },
  ]);
  assert.deepEqual(results.map(({ name }) => name), ["Cursor"]);
});

test("browser pagination preserves sort order, clamps stale pages, and handles empty results", () => {
  const rows = Array.from({ length: 126 }, (_, index) => ({ ...accountFixtures[0], id: `account-${index}`, name: `Company ${String(index).padStart(3, "0")}` }));
  const sorted = sortAccounts(rows, "name-desc");
  const second = paginateAccounts(sorted, 2, 25);
  assert.equal(second.accounts[0].name, "Company 100");
  assert.equal(second.start, 26);
  assert.equal(second.end, 50);
  assert.equal(second.pageCount, 6);
  assert.equal(new Set([...paginateAccounts(sorted, 1, 25).accounts, ...second.accounts].map(({ id }) => id)).size, 50);
  const last = paginateAccounts(sorted, 6, 25);
  assert.equal(last.accounts.length, 1);
  assert.equal(last.end, 126);
  const resized = paginateAccounts(sorted, 6, 100);
  assert.equal(resized.page, 2);
  assert.equal(resized.accounts.length, 26);
  const empty = paginateAccounts([], 5, 25);
  assert.deepEqual([empty.start, empty.end, empty.page, empty.pageCount], [0, 0, 1, 1]);
});

// The design build parsed `profile` off its settings contract. The platform has
// no settings feature, so the shape is restated here — this pins it against the
// profiles the accounts data layer actually produces (fixture person, neutral
// live person, session person), so the substitution cannot silently drift from
// `model/workspace-profile.ts`.
test("the response contract accepts every workspace profile the data layer serves", () => {
  for (const profile of [
    workspaceProfileFixture,
    workspaceProfileForUserId("priya@clue.example", workspaceProfileFixture.avatarColor),
  ]) {
    assert.deepEqual(WorkspaceProfileSchema.parse(profile), profile);
  }

  const response = {
    accounts: [],
    availableAccounts: [],
    profile: workspaceProfileFixture,
    bulkCapabilities: DISABLED_ACCOUNT_BULK_CAPABILITIES,
  };
  assert.deepEqual(ProjectAccountsResponseSchema.parse(response), response);
  // The project table's controller reads capabilities off this document, so a
  // response without them is a contract violation, not a closed-actions table.
  assert.throws(() => ProjectAccountsResponseSchema.parse({ ...response, bulkCapabilities: undefined }));
});
