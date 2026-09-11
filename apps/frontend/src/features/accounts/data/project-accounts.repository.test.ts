import assert from "node:assert/strict";
import test from "node:test";
import { readAccountDirectory, getProjectAccountDirectory } from "./project-accounts.repository";
import { accountFixtures } from "./accounts.fixture";

test("the directory resolves backend cursor pages before browser pagination", async () => {
  const requests: Array<string | undefined> = [];
  const rows = await readAccountDirectory({ projectId: "campaign" }, async (query) => {
    assert.equal(query?.projectId, "campaign");
    requests.push(query?.cursor);
    return query?.cursor
      ? { data: [accountFixtures[1], accountFixtures[2]], meta: { total: 3, nextCursor: null } }
      : { data: [accountFixtures[0], accountFixtures[1]], meta: { total: 3, nextCursor: "next" } };
  });
  assert.deepEqual(requests, [undefined, "next"]);
  assert.equal(rows.length, 3);
});

test("a repeated backend cursor fails rather than looping or presenting a partial count", async () => {
  await assert.rejects(readAccountDirectory({}, async () => ({ data: [], meta: { total: 10, nextCursor: "same" } })), /repeated/);
});

// The default list read is the platform's own `getAccounts`, which chooses
// fixtures or the live HTTP adapter from the accounts fixture switch. The
// design build had no such switch, so this case pins it on explicitly rather
// than reaching for the network.
test("project members are excluded from the add-accounts picker", async (t) => {
  const previous = process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
  process.env.CLUE_ACCOUNTS_FIXTURE_MODE = "true";
  t.after(() => {
    if (previous === undefined) delete process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
    else process.env.CLUE_ACCOUNTS_FIXTURE_MODE = previous;
  });

  const { accounts, availableAccounts } = await getProjectAccountDirectory("custom-reports");
  assert.equal(accounts.length, 5);
  assert.ok(!accounts.some((member) => availableAccounts.some(({ id }) => id === member.id)));
  assert.equal(accounts.length + availableAccounts.length, accountFixtures.length);
});
