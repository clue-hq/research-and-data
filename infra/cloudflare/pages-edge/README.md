# pages-edge

Cloudflare Worker on the `cluehq.page` zone (runbook §9, founder rulings 2026-10-15/16): forwards every workspace address (`<label>.cluehq.page`) and every Cloudflare for SaaS custom hostname (customers' own domains, CNAMEd to `cluehq.page`) to the page origin, stamping `X-Clue-Public-Host` (the visitor's hostname) and `X-Clue-Edge-Auth` (the shared secret). Only GET and HEAD are forwarded. `cluehq.ai` (the app) carries no route and no page traffic.

`LEGACY_SYSTEM_SUFFIXES` is empty at launch (no `*.pages.cluehq.ai` address ever served in production). A later move to another domain lists the old suffix there, and the Worker then answers an old `<label>.<old suffix>` request with a 301 to the same path on `<label>.<SYSTEM_SUFFIX>`; see `docs/specs/pages-hosting-runbook.md` §8.

Deploy with `npx wrangler deploy` from this directory (see the Task 14 runbook; no deployment happens from the repo checkout automatically).

`npx wrangler secret put EDGE_SECRET` — its value must equal `CLUE_PAGES_EDGE_SECRET` on the Railway page-origin service, or every request is rejected.

Tests: `node --test 'infra/cloudflare/pages-edge/*.test.js'` from the repo root (Node >= 18; on Node >= 22 a bare directory argument is not accepted by the test runner).

`EDITOR_SUFFIX` (review finding K3-8): the site editor's domain (`edit.deeppresence.ai`). Its hosts always pass through untouched, so published pages on the editor's registrable domain can never send editor traffic to the page origin.
