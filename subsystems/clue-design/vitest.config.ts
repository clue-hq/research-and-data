/**
 * Guard: there is no repo-root test suite. The editor suite lives in
 * apps/editor and MUST run from there (`cd apps/editor && npm test`) so its
 * vitest.config.ts (react JSX plugin, jsdom, "@" alias) is loaded.
 *
 * A bare `npx vitest` from the repo root silently falls back to an
 * npx-cached, config-less vitest: no jsdom (environment ~0ms), no JSX
 * transform — every .tsx test file "fails" with "Unexpected JSX
 * expression" pointing at valid code. That failure mode burned real time
 * in increments 2b and 2c; this file turns it into one clear error.
 */
throw new Error(
  "No test suite at the repo root. Run the editor suite from apps/editor: " +
    "`cd apps/editor && npm test` (vitest needs apps/editor/vitest.config.ts " +
    "for JSX + jsdom; a root-level run loads no config and spuriously fails " +
    "every .tsx file)."
);
