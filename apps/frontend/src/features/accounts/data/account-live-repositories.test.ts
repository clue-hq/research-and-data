import assert from "node:assert/strict";
import test from "node:test";
import { getAccountContacts } from "./account-contacts.repository";
import { getAccountDetails } from "./account-details.repository";
import { getAccounts } from "./accounts.repository";
import { getAccountWorkspace } from "./account-workspace.repository";

/**
 * D4 Task 2 replaced the pre-re-lift live adapters with the design build's
 * repositories; the amended live adapters land in Task 4, which rewrites this
 * file against them. What still holds today is the one durable rule: with
 * fixture mode off, every account read refuses loudly. A silent fixture
 * fallback on the live path is the failure this guards.
 */
const reads: ReadonlyArray<readonly [string, () => Promise<unknown>]> = [
  ["accounts", async () => getAccounts()],
  ["account details", async () => getAccountDetails("zafran-security")],
  // `getAccountContacts` picks its repository synchronously, so the refusal is a
  // synchronous throw; the async wrapper turns it into the rejection asserted here.
  ["account contacts", async () => getAccountContacts("zafran-security")],
  ["account workspace", async () => getAccountWorkspace("zafran-security")],
];

for (const [label, read] of reads) {
  test(`the live ${label} read refuses instead of falling back to fixtures`, async () => {
    const previous = process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
    delete process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
    try {
      await assert.rejects(read, /accounts live adapter lands in D4 Task 4/);
    } finally {
      if (previous === undefined) delete process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
      else process.env.CLUE_ACCOUNTS_FIXTURE_MODE = previous;
    }
  });
}
