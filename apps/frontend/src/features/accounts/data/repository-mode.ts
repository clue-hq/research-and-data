/**
 * The single place the accounts fixture switch is read.
 *
 * Fixture mode is an explicit, opt-in development flag: the live path must
 * never fall back to fixtures, so a missing or malformed value means "live".
 * No component or repository may read the environment directly
 * (`docs/architecture/frontend.md`); they ask this function instead.
 *
 * This module deliberately does NOT import `server-only`: the sibling
 * `frontend-api.ts` does not either, and the accounts repositories are
 * exercised by `node:test` outside a React Server Component graph.
 */
export function accountsFixtureMode(): boolean {
  return process.env.CLUE_ACCOUNTS_FIXTURE_MODE === "true";
}
