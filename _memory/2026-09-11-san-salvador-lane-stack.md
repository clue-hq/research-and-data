# 2026-09-11 — the san-salvador lane's dev stack (for the founder's manual ARV2 testing)

Branch `track-r4` (O6 + R1–R4 + the D4-b relift), worktree `san-salvador`, DB `clue_san-salvador`
on :55040 at alembic head `2cd622be2da0`. The founder asked for the frontend, the platform API, the
design API and four to five fleet workers with per-worker concurrency, to test every ARV2 feature by
hand, and said the other workspaces' instances could be paused.

## What runs, and how it is started

`./scripts/dev_stack_san_salvador.sh up|down|status` — a wrapper that sets the new `DEV_STACK_*`
knobs and execs the runbook script. **Same ports and login as `DEV_STACK.md`**: frontend
`http://localhost:3020`, design API 8010, platform API 8020 (+ the 8030 twin), four
`clue_api.fleet_main` processes at `CLUE_FLEET_WORKER_CONCURRENCY=3` (the O6 exit-gate ruling:
four processes × three slots). Logs: `/tmp/san-salvador_{design_api,platform_api_8020,platform_api,
fleet_worker,fleet_worker_2..4,frontend}.log`. Agent workspace root
`/private/tmp/clue-agent-workspaces-san-salvador`.

`scripts/dev_stack.sh` gained five env knobs with defaults equal to its previous hard-coded values
(`DEV_STACK_DB_URL`, `DEV_STACK_WORKERS`, `DEV_STACK_WORKER_CONCURRENCY`,
`DEV_STACK_AGENT_WORKSPACE_ROOT`, `DEV_STACK_LOG_PREFIX`), a 6-second stagger between worker
launches, and a macOS-safe worker count in `status` (`pgrep -c` does not exist here). The istanbul
checkout's behaviour is unchanged. `DEV_STACK.md` carries the new section.

Machine-local settings changed for this (all git-ignored): `.env` →
`LUMEN_API_ORIGIN` and `CLUE_DESIGN_API_BASE_URL` to `127.0.0.1:8010`, `LUMEN_API_CORS_ORIGINS`
gains 3020; `apps/frontend/.env.local` → `CLUE_API_BASE_URL=8020`, `LUMEN_API_BASE_URL=8010`,
`CLUE_APP_ORIGIN=http://localhost:3020` (it had been a copy of colombo's 8052/8060/3033).
`CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` already contained 3020. `.env.example` untouched (ports and
origins are deployment-specific; the `CLUE_FLEET_WORKER_CONCURRENCY` default stays 1 — the 3 is a
per-process env set by the script, like its DB override).

Prerequisites built in this worktree for the first time: `apps/frontend` `npm install` +
`design-system:build`; `cargo build -p lumen-api-helper --release` (the other worktrees' binaries
were NOT reusable — `lumen-web` differs from both colombo and istanbul); the vendored
`apps/frontend/public/vendor/tailwind-browser.js` copied from istanbul (git-ignored). Playwright
1.61 with chromium 1228/1234 already present in the shared cache.

## Other stacks stopped (founder: "you may pause the other workspace's instances")

Checked in-flight work first: semarang and colombo had nothing running; istanbul's `clue` DB shows
`design_agent_run running 4 / queued 44` but its worker was driving `clue_istanbul_dev` (the
script's override), which had one queued task only — stale rows, nothing was being driven. Killed by
pid: istanbul (3020/8010/8020/8030 + worker), colombo (3033/8052/8060 + worker), semarang
(3040/8070 + four workers). **Left running:** the port-of-spain dummy frontend on :3000 (the
presentation-truth reference). To bring istanbul back, `down` this lane first — same ports.

## Verification

`status` → all four ports UP, `fleet-worker: UP (4 process(es), 3 slot(s) each)`; each worker log
shows three `worker.slot_start` and zero tracebacks; `fs_root` = this checkout's `.artifacts`;
`GET :8020/auth/v1/session` → 401 (auth surface alive); `GET :8010/openapi.json` → 200;
`GET :3020/` and `/sign-in` → 307 (Clerk redirect, expected before sign-in); no "address already
in use" in any log. The browser walk (sign in → workspace → project → "ping") is the founder's.

## Finding worth a follow-up (not fixed — live run first)

**Fleet worker boot seeds the field registry with plain INSERTs and is not concurrency-safe.** Four
workers started together: three died at boot on
`asyncpg.exceptions.UniqueViolationError: duplicate key value violates unique constraint
"field_definition_pkey"` (the `core.account_name` seed row), the fourth won and ran. Reproducible
on any fresh multi-worker start; the semarang stack never hit it because its workers were started
by hand, one after another. The stagger in the script is the mitigation; the seed should become
`INSERT … ON CONFLICT DO NOTHING` (or take an advisory lock) — owner: whoever next touches the
field-registry seeding in `clue_api` worker wiring.

## Not confirmed here

The worker log does not list its registered kinds, so "the `arv2_discovery` handler is composed in
these four processes" rests on `CLUE_ARV2_DISCOVERY_ENABLED=true` in `.env` and the offline fleet
wiring tests, not on a live line. The first discovery launch (`scripts/launch_arv2_discovery.py`)
proves it.

## Addendum — .env parity and the provisioning flag (founder, 2026-09-11)

First browser walk hit `Provisioning failed with status 404` on the Welcome screen: the Clerk dev
user has no membership in `clue_san-salvador`, the frontend posts to `/auth/v1/provision`, and that
route is mounted only under `CLUE_SELF_SERVE_PROVISIONING_ENABLED`, which was **absent** from the
lane `.env` (default false). Founder ruling: bring `.env` to full parity with `.env.example` and
set `CLUE_SELF_SERVE_PROVISIONING_ENABLED=true` for this lane.

- 33 keys were missing from the lane `.env` (it had only ever served CLI-driven live runs), among
  them `CLUE_FRONTEND_READ_ENABLED` (default false → every `/frontend/v1` accounts read 404'd),
  `CLUE_MEMORY_ENABLED`, `CLUE_ONBOARDING_V2_ENABLED`, the `CLUE_ARV2_FIT_*` thresholds and the
  `CLUE_ARV2_DISPLAY_*` block. All appended at the example's values in a dated block at the end of
  `.env`; the provisioning flag alone set `true`. Parity now 207 = 207 keys, no extras, no
  duplicates. `.env.example` untouched — its posture line stays `false` (standing checklist item 7
  / master plan §11); the lane's `true` is a local testing choice, not a default change.
- **Pitfall in the parity check:** `grep -oE '^[A-Z_]+='` silently drops every key with a digit
  (`…_V2_…`, `…_C7_…`, `…_ARV2_…`) — use `[A-Z0-9_]+`. The first pass reported 0 missing while ten
  keys were still absent.
- With the flag on, the API process composes the old Stage-0 scrape binder and recon (sync LLM
  calls on the web loop — the CLAUDE.md backlog bullet), and the worker composes the recon handler
  and the official-site crawl enqueuer. That is the old lane's onboarding, on only so a browser
  user can mint a workspace; the new onboarding lane stays behind `CLUE_ONBOARDING_V2_ENABLED=false`.
- Every process reads `.env`, so the whole stack was restarted through the wrapper.

## Addendum — the new onboarding lane on, and the run started by hand (2026-09-11 06:48)

`CLUE_ONBOARDING_V2_ENABLED=true` in the lane `.env` (founder), stack restarted; the API mounts
`/onboarding` and the workers compose the driver. No frontend surface starts the run yet (O6
follow-up 4), so it was posted by hand for the provisioned workspace
`ws_2875e9e3dc5c452885db3774076de8c4` (Insight Health AI): run `f4826a17-03a6-4645-9c13-155773921c83`,
lane `onboarding-v2`, fast steps overview / lineup / reviews running at 06:48:09.

**Getting a bearer the API accepts, without a browser.** `POST /onboarding` runs behind the
authenticated resolver: header `X-Clue-Workspace-Id` (not `X-Workspace-Id`) plus a Clerk *session*
token whose `azp` is in `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES`. Backend-API-minted tokens
(`api.clerk.com /v1/sessions/{sid}/tokens[/template]`) carry **no `azp`** and are refused
(`SESSION_INVALID`). What works, against the dev instance's Frontend API
(`https://precise-lamb-56.clerk.accounts.dev`), browser mode with a cookie jar and
`Origin: http://localhost:3020` and **no** Authorization header (Clerk forbids both):
1. `POST /v1/dev_browser` → `token`; pass it as `?__clerk_db_jwt=<token>` on every call
   (without it every call is `dev_browser_unauthenticated`).
2. `POST /v1/client/sign_ins` (`identifier`, `password`, `strategy=password`) → `needs_second_factor`
   with an `email_code` factor (the `email_address_id` is in the response).
3. `POST …/sign_ins/{id}/prepare_first_factor` (`strategy=email_code`, `email_address_id`), then
   `attempt_first_factor` (`strategy=email_code`, `code=424242`, the fixed `+clerk_test` code)
   → `complete`, `created_session_id`.
4. `POST /v1/client/sessions/{sid}/tokens` → `jwt` with `sid`, `azp=http://localhost:3020`.
The token lives ~60 s; the client cookie jar and dev-browser token are reusable to mint another.
Credentials are the founder's and are never written down here.

## Addendum — discovery criteria now come from the ICP itself (founder ruling 2026-09-11)

First discovery launch from the Head of ABM on the Insight Health project was refused
`unknown_criteria_gate_key 'geography'`: `CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS` shipped with the
Clue ICP's keys (`geography,stage`) as a *deployment* default, the tool exposes no key argument,
and the synthesised ICP names its gates its own way (`industry_specialty_ambulatory`,
`geography_us`, `referral_or_document_front_door`, `ehr_in_supported_set`, `hipaa_covered_entity`).
An R4 design mistake: a global default can only ever match one document.

**Ruling:** no default gate criteria anywhere; the gates are decided per ICP. **Landed:** the
setting defaults to empty (operator override only; `.env.example` and the lane `.env` cleared);
`compile_brief(front, body, criteria_gate_keys=())` chooses the gates the document marks
`criterion: true` (new optional per-gate front-matter flag, `Gate.criterion`), else its first three
gates in document order, refusing more than three either way; named keys (request / CLI
`--criteria-gates` / env) still win and are validated against the document; the launch now
records the *resolved* keys on the run row so every attempt compiles the same criteria.
Verified: `tests/arv2/test_discovery_brief.py` (10, incl. a synthesised-ICP fixture),
`test_settings.py`, `test_discovery_driver.py` offline (47 passed, no env);
`test_discovery_launch_db.py` + `test_discovery_driver_db.py` + `test_discovery_store_db.py` on the
lane DB (13 passed); ruff clean. Ledger rows A10 (fixed), A11, A12 added. Follow-up A12: the ICP
synthesis skill should mark the page-answerable gates as criteria so the choice is the author's,
not document order.

Also seen in that chat: the agent retries `submit_ingestion@1` on a *captured user message* every
turn (it reads the `user_turn` onboarding-input captures as "an upload") and is refused by the
executor's compatibility check — every one of the six pins it needs resolves active by hand, so
the failing rule is most likely the duplicate-request rule on the turn's own `artifact_input`
pin; the executor logs only the one-line summary. Ledger A11.

## Addendum — rulings 7′ and 8′: global fit, default membership (founder, 2026-09-11)

The first discovery run on Insight Health (`90817069…`, 34 verified, $2.55, 16 min) landed on the
accounts table with **empty Overall fit / Fit score**: the list served only the primary project's
score (FI-2 §7) and a discovered candidate belonged to no project until approved (ruling 6′).
Founder rulings: **7′** a fit is global to the account (ICPs barely vary; show the newest score
whichever project scored it, membership or not); **8′** a discovered account belongs to the
project that launched the discovery by default, adding it to other projects stays explicit
(supersedes 6′). No backfill — the founder added the 34 by hand.

Landed: `accounts_list.account_fit` (replaces `_primary_project_fit`; the detail read uses it too
and no longer reads memberships); the driver calls `ensure_project_accounts(...,
added_via="discovered")` in the same transaction as the account row and claims; unit fake
`_Memberships` + assertions; DB assertion on `project_account`; both frontend-read fixtures now
write the lower non-primary score first so the higher primary score is the newest (the assertions
are unchanged). Docs: substance §9 rows 7′/8′, README (dedupe paragraph, approval paragraph, the
6′ bullet struck through), ledger A13 fixed + F2/C5 updated. Verified: driver unit 25, driver DB +
list + detail + bulk 53 on the lane DB, ruff clean. Also: `.env.example` carries an uncommitted
`CLUE_ONBOARDING_V2_ENABLED=true` change that is not mine — left unstaged.

## Addendum — auth refusals are now named in the log (founder request, 2026-09-11)

The founder's browser was bounced from `/` to `/onboarding/profile` (the *provisioning* screen,
not the research onboarding) although the `arv2` user is linked, active and an owner: the API
answered the session probe 403 and logged only the status line, so which Clerk subject was
refused — and why — could not be read. A fresh token for the linked subject probed 200, so the
browser had presented a token for a subject the lane DB does not know (Clerk keeps several
signed-in accounts per browser; the dev instance is shared across every checkout). Closed the
gap: `PrincipalError` carries optional `subject` (verified provider subject) and `user_id`; the
resolver and authorizer set them; the handler logs `auth.principal.refused` (method, path,
code, status, subject, user_id) on every refusal. Response bodies unchanged. `tests/auth` 50
passed on the lane DB; mypy clean on the three modules. Ledger A14.

## Addendum — rulings 9′ (mark-type logo) and 10′ (creator is owner), 2026-09-11

PoC over the first Insight Health run (34 companies): Websets `logoUrl` present for all; 22 are
LinkedIn company marks (`media.licdn.com/…/company-logo_…`, non-expiring `e=2147483647`), every
one inspected correct; the site-hosted rest were wrong about half the time (Open Graph banner,
social photo, team photo, page hero); one LinkedIn default placeholder, one 403. Brandfetch's
**logo-link CDN redirects to its docs for our client id** (open: check the id in the Brandfetch
dashboard); the **Brand API with `BRANDFETCH_API_KEY` works** and returned an `icon` for 5/7
misses (Inova's symbol, Southern Ortho's tree verified by eye), wordmark-only for 2.

Founder rulings: show the **mark only** on the accounts list, the account detail and the contact
profile; Websets' LinkedIn mark first, Brandfetch `icon` second, else the placeholder; **creator
is owner by default**. Landed: `core.logo_url` core field + `exa_websets` manifest v4 +
`brandfetch` manifest; `arv2/logo_resolution.py` (`websets_mark_url`, `BrandfetchClient` through
the provider caller, `icon_from_brand`); driver `_resolve_logo` (one Brandfetch hop at most per
candidate, never fails a candidate) + `insert_account_entity(owner_user_id, created_by_user_id)`
stamped with the run's requester; `frontend_read/account_logo.py` streams the image (https only,
raster only, ≤2 MB, 404 otherwise) and the three reads serve `/api/clue/frontend/v1/accounts/{id}/logo`;
four frontend `<Image>` sites get `unoptimized` (session-authenticated route). Secrets:
`CLUE_BRANDFETCH_API_KEY`; settings `CLUE_BRANDFETCH_API_BASE_URL` / `_TIMEOUT_S`.
`scripts/backfill_discovery_run_logos_and_owners.py` applied both to run `90817069…`: 34
owners/creators stamped, 31 logos (22 Websets marks, 9 Brandfetch icons), 3 without a mark
(cancerleukemia, mississippisportsmedicine, orthospecialty — Brandfetch has only wordmarks or nothing).
Tests: driver unit (5 new), `test_logo_resolution.py`, `test_frontend_read_account_logo.py`,
list/detail/driver DB assertions; sources suite green on a fresh DB (the lane DB's `apollo`
manifest row is stale data, a pre-existing red like the answer-key ones). Frontend `tsc` reds in
`features/projects/*.test.ts` are pre-existing (untouched files).

**Owner backfill, second pass.** The run's ``requested_by_user_id`` was ``svc_execution_worker``
(the deepagent launched it on the fleet; every ARV2 launch tool stamps ``ctx.actor_id or
ctx.actor``), so the first backfill hit the ``platform_user`` FK. Fixed the discovery launch to
resolve the launching turn's human (``agent_turn_submission.submitted_by_user_id`` via
``ctx.action_ref`` when ``ctx.principal_kind == "service"``), the driver to stamp owner/creator
only for a platform user, and the script to take ``--owner-user-id``; re-ran with the founder's
user: 34 owned, 31 logos. The nine Brandfetch hops of the first pass were **not ledgered** (the
drain failed after the claims committed) — ledger A18. R2's two launch tools carry the same
service-principal attribution — ledger A17.

## Addendum — Brandfetch: the Logo API only (founder, 2026-09-11, same day)

Founder: "for Brandfetch we only want to use the Logo API … do not use the Brand API, it is
overkill." The Logo API docs (https://docs.brandfetch.com/logo-api/overview) settle the design:
it is a **free, embed-only CDN** keyed by a public client id (`?c=`), `type/icon` is the mark,
`fallback/lettermark` a first-letter tile; **programmatic fetches are refused** — our earlier
probe was bounced `302 x-bf-error: automated_traffic`, which a valid client id does not exempt
(so the client id we hold is fine; the CDN just refuses scripts). Consequences landed:
- The Brand API client, `CLUE_BRANDFETCH_API_KEY`, `_API_BASE_URL`, `_TIMEOUT_S` and the
  `brandfetch` source manifest are gone; `CLUE_BRANDFETCH_CLIENT_ID` (a setting, public) is new.
- `logo_resolution.py` is now two pure functions: `websets_mark_url` (LinkedIn company mark →
  stored `core.logo_url`, streamed by the platform route) and `brandfetch_logo_url(domain,
  client_id)` (`cdn.brandfetch.io/domain/{domain}/w/128/h/128/fallback/lettermark/type/icon?c=…`),
  built by the reads at display time for any account with a domain and no stored mark — never
  fetched, never stored. The driver stores LinkedIn marks only; the logo route streams LinkedIn
  marks only.
- The contract's `logo_path`/`account_logo_path` are `AssetRef` (rooted path OR absolute URL); the
  three frontend Zod models admit `https://cdn.brandfetch.io/…`; `<Image unoptimized>` already
  covers the external host. `DisplayPages.settings` exposed so the contacts read can build the URL.
- The nine Brand-API claims of the first backfill were retired (`verification_status='rejected'`);
  the lane DB's `core.logo_url` field row was corrected by hand to the shipped one-source seed (a
  fresh DB seeds that shape; the registry refuses a same-version redefinition). Ledger A16/A18.
Tests: logo_resolution 8, driver unit 30, settings, requester 3, import guard offline; driver /
launch / store / list / logo route / detail / contacts / field registry DB suites 95 on the lane
DB; mypy and ruff clean; frontend lint + tsc clean on the touched files.

## Addendum — the Target accounts tab lifted from the dummy (SDD, 2026-09-11)

Plan `docs/superpowers/plans/2026-09-11-target-accounts-tab-lift.md`; Opus implementers, controller
reviews, one Opus whole-branch review + one fix wave: commits ea76c9c32..15a875c83 on `track-r4`.
The dummy (`clue-frontend/port-of-spain` @ `e3bcea7`) is presentation truth — every copied file
byte-diffed against it by the final reviewer; only the seams changed: the BFF route composes our
accounts repository (`projectId` filter), the session-derived workspace profile (no settings
feature here) and the bulk capabilities; "Add accounts" writes real memberships through
`addSelectedAccountsToProject` (per-subject reflection, session-expired redirect, server notice);
`projectTargetAccountsHref` never emits `thread-primary` (R3) — threadless → `/projects/:id?surface=target-accounts`
and the landing route canonicalises; a `table` gallery card opens the surface (`gallery-card-target.ts`).
Two pitfalls worth remembering: `git apply` from a subdirectory silently ignores patch paths outside
it (use `--directory=` from the repo root), and `npm test`'s glob cannot match a `[segment]` test
directory (a test there collects zero tests — keep route tests beside the segment dir). Gates:
2203 tests, lint, tsc (50 pre-existing errors outside the two features), build, all green. The
founder's signed-in walk is owed (Task 4 report's 10 steps; the tab, preview, Open as page, Add
accounts + reload); the dev stack serves the new routes (307 to sign-in when signed out).

## Addendum — Target accounts tab: "Add to chat" into the open chat (2026-09-11, evening)

Founder request after the tab lift: the tab's selection bar gets an "Add to chat"
button (global bar's `Button` token at size `md`, but the filled default variant —
"black CTA" — per the founder; the dummy has no such button on this tab). Done
directly (founder: "if it's a small thing do it yourself").

Design: the global action minus its destination picker. New hook
`features/projects/hooks/use-add-to-open-chat-controller.ts` runs the same
`composer-context/prepare` against the current project + `chat.activeThreadId`
and hands the prepared entities to the workspace controller's new `addEntities`
(pure merge `addComposerContextEntities` in `model/chat-context-handoff.ts`);
a refusal goes to the new `failContextHandoff`, i.e. the conversation's existing
handoff-error line, worded by the now-exported `addToChatFailureMessage`. The
callback rides `chat-surface → ArtifactStage.onAddAccountsToChat →
ProjectTargetAccounts.onAddToChat`; absent (artifact route, fixture transport,
no `composerCapabilities.contextRefs`) the button is not rendered. Selection
clears only on acceptance. No handoff record, no navigation.

Gates: 2208 tests green, lint 0 errors (2 pre-existing warnings in
`design-editor/engine/scene/canvasOperations.ts`), tsc at the 50-error baseline,
`next build` green. Contract: `apps/frontend/docs/api-contracts/accounts.md`
§ "Seam edit 3". Owed: the founder's signed-in walk (select rows on the tab →
Add to chat → chips in the composer → send).

## Addendum — verification posture hid the research from the pages (2026-09-11, night)

After the first real deep-research run (run `143d86bf…`, 2 accounts + 10 committee people,
$12.77, all completed) the account pages stayed thin. Cause: the lane `.env` had
`CLUE_VERIFICATION_ENABLED=true`; `arv2/display/gather.py` drops every tier-4 claim that is not
`verified` under that posture, and no ARV2 verifier exists, so all `agent`/`structuring` claims were
filtered before the writer model saw them (Prevea why-they-fit prompt: 5 claims of 79). Proof is in
the raw prompts under `.artifacts/arv2/raw/openrouter/…display-overview-why-they-fit…`. R0 step 5
had set the flag off; the 2026-09-09 parity commit propagated it back on. Founder flipped both env
files to `false`; I added `restart-api` to `scripts/dev_stack.sh` (restarts only the two
`projections_main` twins; workers keep their settings until down/up) and restarted. Because
`stale_sections` has no posture reason, I retired the 16 live blocks of the two researched accounts
and their contacts by hand so the next open regenerates. Ledger: A19 (posture), A20 (posture ≠ stale),
A21 (fit verdicts reach no recipe). Owed: founder opens Prevea / Mid State and confirms the
sections now cite the research.
Fleet workers cycled too (founder, same night): new runbook verb `restart-workers` respawns the
wrapper's 4 × 3 with the stagger, after a `work_lease` in-flight check; all four booted clean with
`CLUE_VERIFICATION_ENABLED=false`. The whole stack now runs on the new posture.

## Close-out — PR #54 merged (2026-09-11, night)

`track-r4` (48 commits: R4 discovery, the Target accounts tab + Add to chat, logos, auth refusal
logging, the lane-aware dev stack, ledger A1–A21) merged into `integration/design-improvement` as
PR #54 (`7949a63e6`). This worktree now sits on `track-r4-v1`, cut from that merge; the lane stack
(`./scripts/dev_stack_san_salvador.sh`) keeps running from this checkout unchanged. Open items are
the ledger's: A1, A2, A3–A5, A11, A12, A17, A18, A20, A21 and the owed founder walks (Target
accounts tab, logos, the regenerated Prevea / Mid State pages under verification-off).

## 2026-09-12 — planning session on `research-streaming`; A2 fixed

Six items discussed with the founder; three approved designs written as specs under
`docs/superpowers/specs/2026-09-12-*`: discovery streaming (verified rows land on the Target
accounts tab as Exa finds them; polling both ends; gates parallel + candidate pool with
`CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY`), the research progress card (pinned above the
composer, one per project, four stage quarters, real stage order deep→synthesis→committee→member),
and onboarding-v2-as-default (setting-up screen on `POST/GET /onboarding`, release after the four
fast steps, legacy recon behind its own flag). Brand-context polish moved to branch
`brand-context-polish` (local, off the base) with rulings: uniform 32 px rows + single-pass hover
marquee, react-markdown + remark-gfm for rendering, CodeMirror for editing (ENG-181/182/183).
Media question answered: podcasts DID run (5 feeds, 2 transcriptions) — hidden by the verification
posture and only surfaced on contact pages; YouTube path never transcribes by design.

**A2 fixed:** `load_research_packs` takes `pg_advisory_xact_lock(2794525886)` and refuses to run
outside a transaction; `tests/api/test_research_pack_seed_race_db.py` red-proofs the race (a probe
loader that sleeps after its insert); the runbook's 6 s worker stagger is removed.

## Discovery streaming landed (plan 2026-09-12-discovery-streaming)

Driver: per-tick `items()` + task pool under one semaphore (`arv2_discovery_verify_concurrency`,
default 4; 1 = the old serial order, which the positional DB script pins), gates of one candidate
gathered, `record_discovery_progress` per tick. Read: `/frontend/v1/projects/{id}/discovery/current`
— its wire models live in `frontend_read/discovery_status.py`, not `contract_v1.py`, because this
document is snake_case on the wire. Frontend: `useDiscoveryStatus` (5 s while live) in chat-surface
→ spinner on the tab label + `refreshToken` refetch in `ProjectTargetAccounts`;
`discoveryLaunchToOpen` opens the surface on a completed launch part. The DB proof's concurrent
scenario runs on a lock-serialised test connection and proves both candidates land with their
verdicts under a cap of 4; per-connection transaction isolation is the production factory's
property (`clue_db.transaction`), not something that test proves. Owed: the founder's signed-in
walk (launch discovery from chat → tab opens → rows climb → spinner stops).

### Discovery streaming — close-out (2026-09-12, branch `research-streaming`, 2741b0ca9..HEAD)
Executed plan `2026-09-12-discovery-streaming.md` under SDD (Opus implementers, controller reviews,
one Opus whole-branch review + one fix wave). Verified locally: offline driver suite 39 green
(pristine under warnings-as-errors), lane-DB suites green, frontend 2216 tests / lint 0 errors /
tsc at the 50-error baseline / `npm run build` green. NOT pushed. Parked for the founder:
1. **Connection pool sizing** — `clue_db` engine uses SQLAlchemy defaults (5 + 10 overflow, 30 s
   timeout) per worker process; at cap 4 one run can hold ~4–6 connections and the lane runs
   4 workers × 3 slots. A checkout timeout inside `_hop`'s shielded drain would lose a bought
   call's ledger row (loud `needs_review`, not silent). Decide: size the pool via new env flags,
   or keep cap × slots under 15.
2. Follow-up options, not defects: a candidate-slot cap so rows stream steadily instead of in
   bursts (one shared semaphore is breadth-first); list the webset only when the view's found
   count moved (per-tick listing ≈ one ledger row + raw body per 15 s); a client ceiling for a
   run stuck at `not_started`.
3. Owed: the founder's signed-in walk after these fixes — launch discovery from chat → tab opens
   → rows climb → spinner stops — including a page reload mid-run.

## Research progress card landed (plan 2026-09-12-research-progress-card)

`arv2_research_job.stage` (migration `c90aaea30a88`, off `2cd622be2da0`), `set_job_stage`, four
driver stamps (claim / finalize tool / committee / member launch), pure fold
`arv2/research_progress.py`, read `/frontend/v1/projects/{id}/research/progress` — its wire models
live in `frontend_read/research_progress.py`, not `contract_v1.py`, because this document is
snake_case on the wire — card pinned in the composer dock. The card is primed on a completed
`launch_arv2_account_research` or `launch_arv2_person_research` tool part (the old lane's
`launch_account_research` is superseded and is not matched). Owed: the founder's walk (launch
research → card appears within 5 s → bar and line move → Completed for 60 s → gone).

### Research progress card — close-out (2026-09-12, branch `research-streaming`, 1d033d924..HEAD)
Executed plan `2026-09-12-research-progress-card.md` under SDD (Opus implementers, controller
reviews, one Opus whole-branch review + one fix wave). Verified locally: offline arv2 suites 178
green, lane-DB suites green (migration `c90aaea30a88` applied to the lane DB), frontend 2224
tests / lint 0 errors / tsc at the 50-error baseline / build green. NOT pushed. For the founder:
1. **Provisional ruling R11** — a run kept alive only by `needs_review`/`suspended` jobs drops off
   the card 24 h after its last job finished (`ATTENTION_LINGER_S`); nothing in the system moves a
   job out of `needs_review` and the card has no dismiss control, so the spec's exit was
   unreachable. One constant to move if a different window is wanted.
2. **Spec-faithful but static bar (I5)** — `committee`/`member_research` commit with `finish_job`,
   so a running account job shows 0 % through the whole deep-research phase, then jumps; the
   "Finding the buying committee" line is unreachable for account agents. An earlier stamp is a
   spec change; decide on the walk.
3. **C1 fix unseen in a browser** — the composer dock now sizes to content when the card shows
   (`composerDockWithResearchCard`), proven by the flex chain and a contract test only. The walk
   must confirm: card visible, composer usable, 8 px gap and full-frame width acceptable.
4. Owed walk: launch research → card within 5 s → bar and line move → Completed for 60 s → gone;
   a person-only launch (card scores by people); a worker restart mid-run (paused jobs score only
   their walked quarters, pill "Needs attention"). Workers need a restart to pick up the stamps.

## Onboarding v2 is the default (plan 2026-09-12-onboarding-v2-default)

`CLUE_ONBOARDING_V2_ENABLED=true` by default; `CLUE_LEGACY_STAGE0_RECON_ENABLED=false` gates the
old recon (binder, `/stage0/setup`, STAGE0_RECON handler). The setting-up screen posts
`/api/clue/onboarding` and polls `/api/clue/onboarding/current`; release on the four fast steps.
(The brand-context status route named in ledger row F1 was the earlier idea; the plan used the
onboarding route.) The profile draft is memory-only, so a hard reload on the setting-up screen
re-attaches to a live run via the seam's probe but cannot start one — founder call whether to
persist the website. Ledger A3/A4/A5 closed. Owed: a fresh-workspace walk (sign up → profile →
setting-up fills from the new lane → released → Brand context shows the documents, personas
landing after).

### Onboarding v2 default — close-out (2026-09-12, branch `research-streaming`, a4e5675b5..HEAD)
Executed plan `2026-09-12-onboarding-v2-default.md` under SDD (Opus implementers, controller
reviews, one Opus whole-branch review + one fix wave). Verified locally: offline composition/flag
suites green, lane-DB stage0/brand-kit/onboarding-route suites green, frontend 2207 tests /
lint 0 errors / tsc at the 50-error baseline / build green. NOT pushed. Restart the platform API
and workers to pick up the flag split (the lane `.env` now carries
`CLUE_LEGACY_STAGE0_RECON_ENABLED=false`, so the old recon no longer composes).
Fix-wave outcomes worth knowing on the walk: `completed_with_gaps` now reads as complete (it was
"unavailable"); a fast kind moved to the background phase never gates the release; a failed fast
step shows the failure only once all four fast steps have settled (R6); `GET /onboarding/current`
gained an additive `brandKitIngestion` so the "Creating brand kit" row moves again (R5); the
audience row's "personas continue" note now shows from the release tick.
Owed walk: fresh workspace → sign up → profile → setting-up fills from the new lane → released on
the four fast steps → Brand context shows the documents, personas landing after; plus a hard
reload on the setting-up screen (memory-only draft → the seam re-attaches to the live run).
Parked: the fixture (design-review) preview now shows the five live rows; the official-site crawl
fleet still composes unconditionally (inert without the recon handler); persisting the profile
website across reloads is a founder call.

## 2026-09-12 — project context + ICP authoring: spec and four plans written (not yet executed)

Founder walk findings: a second thread of a project knows nothing of the first (the `project_state`
route of `record_interview_answer` is write-only since O6 ruling D5; L6 is thread-scoped; no ARV2
list/read tools on head-of-abm@v45), and skill v22 §3/§5/§10 forbids ICP authoring. Founder rulings
R1–R9 recorded in `docs/superpowers/specs/archive/2026-09-12-project-context-and-icp-authoring-design.md`.
Presentation truth for markdown documents = the dummy's Plan tab (screenshot 2026-09-12); this repo's
`project-plan.tsx` / `ProjectPlanSchema` are orphaned dummy lifts (zero importers) and get replaced.

Plans, in build order (each SDD-executable on its own):
1. `docs/superpowers/plans/2026-09-12-project-context-files.md` — `agent_turn_project_files` pin,
   `inputs/project/status.md` + `decisions.md` (deterministic), `ProjectFilesIndexCard@1`.
2. `docs/superpowers/plans/2026-09-12-icp-authoring.md` — `brand_knowledge_document.project_id` +
   `derived_from_document_id`, `onboarding_run.kind`, `author_icp_document@1`,
   `request_persona_synthesis@1`, skill v23 / profile v46 / recipe v24.
3. `docs/superpowers/plans/2026-09-12-project-plan-document.md` — `write_project_document@1`,
   `/frontend/v1/projects/{id}/documents` list/detail/PUT, the Plan rail surface, shared markdown
   pieces on design tokens, auto-open + plan-card click, documents in the gallery, skill v24 / v47 / v25.
4. `docs/superpowers/plans/2026-09-12-head-of-abm-read-tools.md` — `read_project_accounts@1`,
   `read_account_research@1`, `read_discovery_run@1`, skill v25 / v48 / v26.

Also observed today: 32 Exa `402 Payment Required` responses in the workers' logs during the research
run (jobs still finalized; content fetches were refused). Exa credit likely exhausted — founder told.
