# Project Memory

This directory is the durable collaboration log for agents working on this repository.

At the start of each session:

1. Read this file.
2. Read the newest session note(s).
3. Read any topic note that matches the current task.
4. Verify memory-derived facts against the current workspace before editing.

During and at the end of each coding or goal session, update `_memory/` with:

- progress made;
- files changed;
- decisions and accepted assumptions;
- failures, blocked attempts, or commands/tests that did not work;
- verification performed;
- unresolved follow-ups.

Keep notes concise and operational. Do not store secrets, API keys, credentials, customer data, or raw proprietary source excerpts here.

## Repository Role

- `2026-09-22-asset-inspector-review.md` — branded asset inspector, automatic saving,
  responsive/failure verification and pilot comparison with an open generation-quality defect.

This repository is the data and research subsystem for the larger AI-native ABM orchestration platform. Its job is to turn client ICPs and client knowledge into canonical account/contact entities, typed claims with provenance, explainable fit/intent scores, and persona-keyed buying-committee research that downstream content and design systems can trust.

The central architecture bet is that verification must be modeled at the claim/data layer. LLM research is a last-resort tier-4 source, not the foundation. The product should prefer empty, flagged fields over fabricated fields.

## Topic notes
- `2026-10-05-stranded-research-jobs-lease-takeover.md` — root cause of the stranded `suspended` ARV2 jobs (sync model-catalogue fetch froze the worker loop 105 s; re-offered task closed as no-op; frozen worker then parked the job), fixed by catalogue fetch off-loop with a real deadline, lease-holder takeover in `begin_job` + attempt-fenced `finish_job`/`suspend_job`, a dry-run repair script, and the "paused, resuming automatically" card text. Reproduced and re-verified live on a clone of `clue_trenton`. **trenton's two stranded jobs are NOT yet re-offered (founder's call).**
- `2026-09-28-custom-domain-f5-reconciliation.md` — custom-domain publishing × F5 multi-page reconciled on `website/custom-domain` (`8ab2780d4..de80c454d`) under the founder ruling of 2026-09-28: our `workspace_hostname` registry + `clue_page_origin` for storage and serving; F5's multi-page routes (`/{slug}/{route}`) and lock-at-first-publish adopted (`workspace_hostname.locked_at`, `label_locked`); `design_workspace_handle`, the design API's Host app, `/workspace/handle` and `LUMEN_PUBLIC_PAGES_*` removed; handles backfilled into labels by `770bf20802e1` (join `c16e1ae684b3`); `custom_page_urls` on publish responses; Settings → Pages on the settings slice's shell. The merge's 43 conflicts, the seven plan decisions, every ruling, tests per task, inherited reds and deferred minors. **Owed: `npm run build`, the dev-stack walk (two-page site, Settings → Pages, lock refusal), the hosted S0 and live Cloudflare S2 walks, the frames re-lift, the Task 6 exit gate.**
- `2026-09-17-custom-domain-publishing-s2.md` — custom-domain publishing S2 landed on `website/custom-domain` (13 commits `ab3a3bf7b..6e40162af`): the Settings → Pages control plane (`/frontend/v1/settings/pages` — read, defaults, both multipart uploads, Clue-address label, connect/check/remove), `clue_spine` custom-hostname validation + DAL and the pages-settings DAL, the Cloudflare for SaaS client, DNS observation and the pure status ladder, `workspace.manage_settings` (policy revision 3), the page origin's fallback-URL/favicon reads, design-API publish-time description/social-preview defaults, and the lifted settings shell with the four-state custom-domain card; the seven plan decisions, the rulings, the test evidence, the settings-slice merge reconciliation list and the deferred minors. New contract doc: `apps/frontend/docs/api-contracts/settings.md` (Pages section). **The live Cloudflare acceptance walk (spec §10, a founder-owned hostname), the dev-stack walk of Settings → Pages, `npm run build` and the co-founder's frames for the connection card are all OWED.**
- `2026-09-17-custom-domain-publishing-s1.md` — custom-domain publishing S1 landed on `research-streaming-v3` (14 commits `2247d1f8f..4ffd7d3da`): migration `aaff3d831895` (`workspace_hostname` + `workspace_pages_settings`), `clue_spine.hostnames` + allocation in `create_workspace`, `make pages-backfill-hostnames`, the new `clue_page_origin` service (Railway Dockerfile, dev port 8040, edge gate), host-independent publish packages (root-relative `/p-assets`, shared CSP, no canonical/og:url), the O6b `/w/` routes deleted, the share menu on the real host, and the `pages-edge` Cloudflare Worker; the nine plan decisions, the test evidence, and the follow-ups (S2 control plane, reserved slugs not refused at publish, the design subsystem's own `webDocuments.ts`). **S0 is a founder-operated runbook — `docs/specs/pages-hosting-runbook.md` — and NOTHING hosted exists yet; the dev-stack walk, `npm run build` and the hosted acceptance walk (spec §3 item 7) are all OWED.**

- `2026-09-24-nick-person-exa-comparison.md` — second isolated person-depth trial, fresh
  delegation/query, missed personal-discovery benchmark and preserved playground comparison inputs.

- `2026-09-24-person-exa-comparison.md` — isolated person-agent request and paid Exa trial against
  saved PoC; exact artifacts, source-level comparison, role-attribution defect and pending review.

- `2026-09-24-person-exa-charter.md` — explicit person-depth charter and Exa instruction review
  draft; source inspiration and the still-pending person provider/navigation wiring.

- `2026-09-23-head-of-abm-research-briefing.md` — rejected runtime compiler reverted;
  Head-of-ABM briefing skill, shared account placeholders and existing source references.

- `2026-09-23-arv3-advisory-research.md` — founder defers relationship/schema/display verification; source-based selection, plain findings and unrestricted research presentation for new quality revision six.

- `2026-09-22-arv3-research-quality-implementation.md` — authorized quality development in
  progress; exact context foundations, isolated test DB and remaining implementation/acceptance.
- `2026-09-22-arv3-research-quality-spec.md` — detailed review proposal and ordered plan for exact
  project context, evidence access, claim corrections, specialist ownership and committee reconciliation.
- `2026-09-22-arv3-premier-live.md` — authorized isolated Premier v3 run, six-worker fleet,
  completed research/display and tracing, with identity, evidence and seller-context quality defects.
- `2026-09-22-arv3-cumulative-quality-review.md` — Premier v1 / Probook-Zafran v3
  comparison, completed historical read-only join, shared extraction/correction defects,
  and conditional Deep Agent specialist design; discussion only.
- `2026-09-22-arv2-media-implementation.md` — approved media v3 implemented locally;
  AI Ark v2 remains default. Observability follow-up repairs unpriced video settlement and
  async trace nesting, adds IDs-only media outcomes; 145 affected tests pass. Live acceptance owed.
- `2026-09-22-arv2-media-research-planning.md` — media spec/plan only, covering discovery,
  reusable transcripts and evidence; separate founder instruction changed new-launch default
  to AI Ark v2. 70 focused tests pass; media implementation and live acceptance remain pending.
- `2026-09-22-arv2-ai-ark-committee-planning.md` — planning-only SMART role discovery within
  researched accounts; founder approved work-email + phone enrichment and continuation after
  Exa failure. Detailed design/plan, profile reuse and identity/replay/context/erasure gaps;
  based on pulled `8df27dd25`. No runtime implementation or live provider calls.
- `2026-09-22-web-search-tool-design.md` — `web_search@1` **LANDED 2026-09-22**, re-minted as head-of-abm@v62 / prompt v15 / manual v9 / recipe 32 on the research-streaming merge (two base heads joined by `7c4fe6965720`; seven stale base tests fixed); (branch `feat/add-general-purpose-web-search-exa`, eight commits `722814d91`..`cd2f9ca91` plus this record): one deep-lite open-web search granted to `head-of-abm@v62` (prompt v15, recipe0-stage0@32, manual v9) and `design@v3` (the fourth tool on the platform-reads seam, both harnesses), used LAST by prompt, text never a claim, ledger row workspace-stamped. Design session rulings, verified seams, spec `docs/superpowers/specs/2026-09-22-web-search-tool-design.md` (implemented; offline acceptance §4.1–4.4 green) and the eight-task plan `docs/superpowers/plans/2026-09-22-web-search-tool.md`; **the two live proofs (§4.5–4.6) are owed, founder-triggered.**
- `2026-09-22-lome-lane-ports.md` — the lome lane (branch `research-streaming-v3`) on its own all-4 ports 3024/8014/8024/8034 via the untracked `scripts/dev_stack_lome.sh`; DB = `clue_lome`@55040, a verified `pg_dump|psql` clone of `clue_san-salvador` (founder ruling, second pass); `.artifacts/`, helper binary and `npm ci` owed before `up`.
- `2026-09-22-on-demand-ingestion-pool.md` — dedicated ingestion coordinator and
  on-demand 4 x 10 image workers; strict routing, durable tasks and idle shutdown.
- `2026-09-22-hide-asset-source-interpretation-rows.md` — temporarily removes Observed
  use, Logo relationship and Messaging & tone from the inspector; stored metadata retained.
- `2026-09-22-asset-vision-replay-preparation.md` — four approved live calls completed;
  all recognized the logos, background interpretation varied, original failure not reproduced.
- `2026-09-22-asset-description-mapping-audit.md` — identity/fingerprint checks and
  concurrent replay pass, but multiple captions are visually wrong; validation,
  transparent-preview, provider-evidence and library-polling gaps remain open.
- `2026-09-22-asset-details-height.md` — asset Details column fills the modal height;
  removed a conflicting viewport-height cap and verified internal scrolling live.
- `2026-09-22-onboarding-role-select.md` — onboarding Role field reuses the branded
  shared select; browser-checked without disturbing the user's live ingestion.
- `2026-09-21-brand-context-controls.md` — shared branded asset selectors, aligned
  toolbar, simplified header, and automatic brand-kit plus ICP/product approval.
- `2026-09-21-san-diego-stack-startup.md` — isolated live San Diego stack on
  3033/8013/8023/8033; four fleet workers, restored blobs, and authority/recipe boot fixes.
- `2026-09-20-pr68-conflict-resolution.md` — PR #68 target-branch merge preserves
  sandbox and project-management authority tests; isolated database migration smoke.
- `2026-09-20-sidebar-action-overlay.md` — project actions overlay full-width names
  on hover/focus instead of reserving empty space in the sidebar row.
- `2026-09-20-remove-chat-tool-activity.md` — release cleanup: removed per-tool step
  activity rows from the shared chat renderer across all conversations and states.
- `2026-09-20-chat-appearance-review.md` — documented CHAT-VIS-01..03 in the canonical
  chat fidelity map: shared body tokens (now 14/22), mention identity and attachment geometry now
  implemented; live/split and isolated responsive browser checks plus 81 focused tests passed.
- `2026-09-20-remove-chat-inspect.md` — release cleanup: removed the chat Inspect button,
  drawer wiring and capability probe; frontend build/lint gates and live browser smoke passed.
- `2026-09-20-sandbox-private-defaults.md` — fixes the CSV permissions incident at creation:
  worker UID/GID + child-only umask 077, defensive-only mode repair, native Linux volume smoke
  and Docker-to-workspace-finalize regression; 144 focused tests passed.
- `2026-09-17-pr62-design-agent-v1-merge-context.md` — merges `origin/research-streaming` into
  `codex/design-agent-v1` (PR #62): the 37-conflict resolution under the founder's rulings, the
  semantic fixes the gates surfaced, the Alembic join, the gateway numeric-code retry follow-up,
  and the triage of seven broad-suite failures (five stale-default-DB, two pre-existing on the
  target). Local commits only; not pushed.
- `2026-09-17-composer-file-tagging.md` — composer `@` tagging of files, microsites and accounts: the approved spec and its rulings (categories Files / Microsites / Accounts, the Gallery is the file system with no path or id ever shown, a tagged design artifact is a reference only and never opens a design leg, latest version offered and pinned on tag), the eight landed tasks on branch `file-tagging` (migration `9289d41e9a60`: wire + CHECK, validation with project containment and `CONTEXT_REF_STALE`, the L5 focus card, the transcript echo, the typed catalog, the two-level picker, the typed chips and contract notes), what the browser walk and the tests proved, and the deferred minors. **Three live proofs owed — founder-triggered: the L5 card in a real turn, a microsite mention answered without a leg, and a stale-tag refusal.**
- `2026-09-17-no-model-pins-in-tests.md` — ruling: tests never assert which model a default/pin names, only that the id is well-formed (`tests/_model_ids.py`); the design@v1 doubled-prefix fix and the six test rewrites; router label follow-up.
- `2026-09-18-conversation-naming-design.md` — generated chat titles + project names: design session (rulings B/A/1, 60 s timeout, default on; off-critical-path grace + bounded poll) AND the implementation record — spec `docs/superpowers/specs/2026-09-18-conversation-naming-design.md` approved and implemented on branch `research-streaming-v3` (Tasks 1–10, commits `1f183eb73`…`cccf7a072`), focused suites green; live acceptance (spec §6 items 1–8, real `CLUE_OPENROUTER_API_KEY`) and `npm run build` still owed.
- `2026-09-18-trenton-lane-ports.md` — the trenton lane (branch `research-streaming-v3`) on its own all-9 ports 3029/8019/8029/8039 via the untracked `scripts/dev_stack_trenton.sh`; `clue_trenton`@55040 cloned from live `clue_san-salvador`; helper binary, `.artifacts/` and the wrapper commit still owed.
- `2026-09-18-lane3-slice5-design-subsystem.md` — Lane 3 slice 5 on `lane3/slice5-design-spend`: the design subsystem's spend, tracing and telemetry on the platform's stack — the provider-caller seam moved to `libs/clue-spend` (ARV2 re-exports), `clue_obs.production` + the `clue-design-api` root, a per-unit `spend_scope` behind the ten `design.*` ledger operations with an injected drain, per-call receipts collected at the invoke config onto `agent_model_call` with `role=design`, and the `design-leg.turn` trace. Includes **finding F-1** (the slice-2 trace carrier broke every QUEUED design job at the `extra="forbid"` envelope parse — 47 failures on 2026-09-17; fixed at the worker) and the **five owed live proofs**, founder-triggered.
- `2026-09-18-lane3-slice5-planning.md` — the planning session behind it (design note + six-task plan, six rulings requested); superseded by the note above for what actually shipped.
- `2026-09-18-workspace-display-names.md` — workspace display names: canonical name from the website's domain, typed-first provisioning, `workspace_name` on the session, chooser + sidebar switcher on real memberships landing on `/`, dry-run backfill; browser-verified; owed: a blank-name provisioning and `--apply` on real environments.
- `2026-09-17-settings-rebase-pr57.md` — rebase of PR 57 (`settings-page` onto `research-streaming`), preserved Settings changes and upstream Artifacts/provider incidents/composer tagging; Alembic joins `4266c7fb8ab1` and `f74cbccd3200`; regression and lease-protected push record.
- `2026-09-15-artifacts-page-exploration.md` — `/artifacts` cross-project artifacts home: the dummy's implementation (port-of-spain `45892a6`+`93c6120`), what this repo has (nav link with no route; per-project leg-derived design-artifact feed + project documents; no workspace-wide list, no metadata writes, no account on the wire) the fifteen founder rulings, and the closing entry: the whole integration LANDED 2026-09-16 (26 commits; migrations 5f2bd1b4b82d + 323081354b51; `/frontend/v1/artifacts` + marks; governed rename/archive tools; `/artifacts` route; `?open=`), gates green first-hand; the browser walk is OWED (founder-triggered, ports held by san-salvador).
- `2026-09-16-workspace-agent-proposals-plan.md` — founder-requested plan for workspace-local automatic research fields; trusted registration, historical global vocabulary containment, Settings creator attribution and immutable deepagent manual/bundle updates. Planning/docs only; no runtime activation.
- `2026-09-16-settings-completion-plan.md` — Settings completion plan after code/spec audit; accepted suspended-member and invite-retry rulings; registry trigger/nullability, retirement fallback and evidence projection gaps; explicit Research fields and Pages V1 phases. Planning only, implementation and live acceptance remain open.
- `2026-09-15-lane3-slice4-entity-tags.md` — Lane 3 slice 4 on `lane3/sice1b`: `tag_entities` (shared per-trace accumulator; `entity:<id>` tags + `entities` metadata); the job tags its subject, its writes and its committee members; `read_account_research`/`read_claims` tag what they served; the erasure query; the 2026-09-15 coverage audit and the leave-as-is ruling. **Live proof + Langfuse retention owed — founder-triggered.**
- `2026-09-15-lane3-slice3-langfuse.md` — Lane 3 slice 3 (3a + 3b) on `lane3/sice1b`: Langfuse attached to the slice 2 provider; the LangChain handler + run registry in the turn and research-agent tuples; gateway/provider/tool observations with settled cost; receipt ids (migration `b7193eb28363`) and ledger-row ids; redaction; `make langfuse-check`; the streamed `answering_model` fix. **Live proof owed — founder-triggered.**
- `2026-09-15-lane3-slice2-roots.md` — Lane 3 slice 2 on `lane3/sice1b`: `clue_obs.otel.install_tracing` (one provider per process, run context on every span, httpx + FastAPI instrumented) and `clue_obs.sentry` installed at `projections_main` and `fleet_main`; run context bound at the roots (the design note's 'already done' claim was false); the trace rides the fleet payload (D1, no migration); `CLUE_OTEL_*`/`CLUE_SENTRY_*`/`CLUE_RELEASE` + the metrics gap in `.env.example`; seven rulings. **Live proof with an OTLP endpoint and a forced Sentry event owed — founder-triggered.**
- `2026-09-15-lane3-slice1b-jsonl-ledgers-to-postgres.md` — Lane 3 slice 1b on `lane3/sice1b`: the onboarding lane, the display prewrite (+ the frontend read seam) and the persona-evidence tool drain their `ProviderCaller` sinks onto `provider_call_ledger` (D1 job = onboarding run id; D2 display spend commits on its own; D3 evidence tool refuses without an artifact store); `openrouter_cost_reader` stamps model + token counts; `not_covered` shrinks to R12 + pre-column rows; eight rulings; the duplicate `-onto-` plan on the base flagged. **Live onboarding run owed — founder-triggered.**
- `2026-09-14-lane3-slice1-cost-read.md` — Lane 3 slice 1 (the cost read) on `lane3/slice1-cost-read`: `agent_model_call.cost_usd`/`cost_source` stamped from the gateway's measured cost, `clue_projections.cost`, `GET /cost/report`, `make cost-report`; proven over 5,958 real ledger rows on the lane DB with zero spend (function = endpoint = CLI); eight rulings; findings (doubled `answering_model` on streamed head-of-ABM turns, model-less `chat/completions` ledger rows, the JSONL ledgers → slice 1b). **The paid live turn is owed — founder-triggered.**
- `2026-09-14-settings-integration-exploration.md` — settings section exploration (dummy at :3000 / port-of-spain is the truth; this repo has no settings feature; per-section backend readiness table; five open founder questions). No code changed.
- `2026-09-14-lane2-flow-closeout.md` — completed Lane 2 frontend verification audit; consolidated acceptance checklist, corrected stale lane-index status, 2,270-test/build evidence and separate pending chat-card visual review. Supersedes pending-status summaries in earlier Lane 2 entries below.
- `2026-09-13-lane2-project-document-connection.md` — Semarang Lane 2 Task 4: authenticated project-document list/detail/save connection, Zod models, version/permission errors, browser-safe save actions, BFF origin checks, orphan removal and 2,245-test verification; shared editor/Plan/Gallery UI still pending.
- `2026-09-09-arv2-onboarding-o6-head-of-abm.md` — O6 landed on `onboarding/o6-head-of-abm` (`3ceb81f36` → `83817317e`): the Head of ABM moves onto the ARV2 onboarding lane — profile `head-of-abm@v44` (prompt v8, skill `stage0-interview@v21`) drops the eleven old-lane tools and adds `open_product_set_selection_gate@1`, `open_icp_confirmation_gate@2`, `launch_arv2_account_research@1` and its read sibling; migration `a3fc75e248e0` pins the brand's knowledge documents per turn (`agent_turn_knowledge_pin`), the pinned bytes are seeded read-only under `inputs/brand/knowledge/` and L3 carries ONE compiled artifact — `BrandKnowledgeIndexCard@1` — while the Client-KB v2, Stage-0 project-state and two product cards leave production composition for every workspace (D5, no flag); recipe v22 re-pins the ICP gate at `@2` and drops `@1`; a confirmation never retires another project's confirmed row. Decisions D1–D12, every execution ruling, the deferred minors, the offline evidence (836 tests, one pre-existing red; one alembic head; db-smoke clean) and twelve follow-ups. **Checklist 6/7 — item 7 fails on `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=true` set by `aa476413e`, not by this lane. The live O6 exit gate has NOT run — founder-triggered.**
- `2026-09-08-arv2-onboarding-o3-catalog-identity-ladder.md` — the O3 follow-up on `onboarding/o3-catalog-identity-ladder`: migration `be9f4984729a` (`model_reused`/`model_unsure` + `reconcile_confidence`/`reconcile_reason`), spine `add_product_aliases`, and the four-rung ladder in `synchronize_catalog` — lineage row, fingerprint replay, spelling key, then ONE batched model reconciliation per run with each entry's `official_url` as evidence (`CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED`). Automatic merge only for the deterministic rungs and `high`-confidence model matches; everything else mints and is flagged `model_unsure` for the human gate. POC evidence 28 → 18 rows, no wrong merge, identical on gpt-5-mini and grok-4.6; founder rulings (no stoplist; a shared page is evidence, never a key); the standing-rule checklist run and all seven items passing. **The live proof (plan Task 6) has NOT run — it is founder-triggered.**
- `2026-09-09-arv2-d4b-arv2-native-reads.md` — D4-b on `track-d4b` (seven tasks, `ef273a666` → `ceb82f841`): the founder ruling **ARV2's own rows are the only truth; the old lane is deleted, never bridged** (now `ARV2-MASTER-PLAN.md` §2 principle 0); research status from `arv2_research_job`, the committee = contacts with live claims (no coverage row), persona as display text everywhere including the stored blocks (one-shot: 7 blocks / 26 personas), revenue/funding/band labels from the registry objects, `core.work_email` as an object carrying the provider verdict (migration `7332ac974920`), **the FI-2 read surface and the `?contract` parameter deleted (39 files, −7,087)** with E6, and the D1 answer-key loader writing ARV2 run/job rows only (guard allowlist now empty); the three idempotent worktree-DB repairs, every ledger ruling and attribution, the close-out gate with a clean-DB A/B attribution method, and the follow-ups (the Phase-6 PR, R3's email object + own committee rows, nullable `linkedinUrl`, `POST /frontend/v1/accounts`, the CSS re-sync job, the `Aakash` shell placeholder, the four pre-existing reds). **Phase-6 inventory written, nothing deleted: `docs/specs/ARV2-PHASE6-LEGACY-DELETION-INVENTORY.md`** (83 legacy tables, ~38 kLOC of modules, an eight-step deletion order, an explicit survive list).
- `2026-09-09-arv2-d4-accounts-relift.md` — D4 on `track-d4`: the design build's accounts feature re-lifted into `apps/frontend` (feature, eight routes, accounts layout shell, favicon proxy, design-system package + the temporary `legacy-compat.css`), the sixteen §6 client-side derivations removed, contract-v1 Zod now the feature's own models **and** the Python parity oracle's source, five adapters on `fetchRead` + the BFF with `?contract=v1`, fixtures only behind `CLUE_ACCOUNTS_FIXTURE_MODE` (never a fallback); the kept FI-2 behaviours (bulk add-to-project / send-to-chat, the single-contact email lookup with its 40-poll ceiling, the typed recovery screen) and the dropped ones; the founder rulings 2a–2j, the ledger rulings, the live checks, the 12-route walk and its **24-item drift list (D5's input)**, and the follow-ups (the backend FI-2 deletion PR, `POST /frontend/v1/accounts`, the CSS re-sync job, the `core.work_email` verdict writer). **No backend behaviour changed.**
- `2026-09-08-arv2-d3-read-surface.md` — D3 on `track-d3`: the five accounts-screen payloads (E1–E5) as **contract v1 selected per request with `?contract=v1`**, the FI-2 payloads and `apps/frontend` untouched until D4; `contract_v1.py` + the vendored Zod oracle, `v1_shared.py`, the `DisplayPages` seam (degrading, background regeneration, `generate=False` for evidence authorisation), the new E3 `/workspace` route; the Zafran walk over the real answer key, the ledger rulings, the standing-rule checklist, and the D4 follow-ups.
- `2026-09-07-arv2-onboarding-o3-fleet-driver.md` — O3 landed on `onboarding/o3-fleet-driver`: the `onboarding_run` fleet kind + artifact-keyed lineage migration `af3cf1541ebe`, the store, the catalog synchronizer, the run driver, `POST /onboarding`, the client-entity binder outside the lane, and the fleet composition behind `CLUE_ONBOARDING_V2_ENABLED`; the lane's rulings, the 7-item standing-rule checklist (all pass), and the acceptance run still owed (Task 7).
- `2026-09-07-arv2-onboarding-o4-synthesis-agent.md` — O4 landed on `onboarding/o4-synthesis-agent`: `AgentRole.ONBOARDING_SYNTHESIS` + migrations `000b9d8bb17b` and `dfb9fa040b13` (the fourth role CHECK, `agent_model_call_role`, as its own revision), `exa_search_evidence@1`, the `onboarding-synthesis-unit@1` recipe, the `onboarding-synthesis@v1` catalog pins, and `OnboardingSynthesisLauncher` composed in `fleet_main` behind `CLUE_ONBOARDING_V2_ENABLED`; the eight rulings; what waits for the O3 merge (the `synthesis=` handoff + `alembic merge dfb9fa040b13 af3cf1541ebe`); the pre-existing red `design@v1` malformed `model_id`; **no live turn has run** (founder-triggered).
- **Live acceptance 2026-09-08 (Insight Health, O3 + O4)** — recorded as the last addendum of the O4 note above: three unseeded runs (~$7.80 Exa + grok tokens); run 1 failed on the profile timeout vs the gateway ceiling, run 2 on the pin provider re-pinning the static skill (`conflicting_requirement`), run 3 fully `completed` (3 ICP + 3 persona documents, 15 evidence calls). Fixes: `fad664b04`, `8fb4c439e` (`CLUE_GATEWAY_TIMEOUT_S`), `046b6ebc3` (`CLUE_AGENT_MODEL_TIMEOUT_S`), `3f8721af6`. **OWED:** the scripted `exa_search_evidence` call in `tests/api/test_onboarding_synthesis_wiring_db.py` is committed unverified; the broad suites have not been re-run since the timeout/pin changes (founder paused suite runs to get the live run back — run them on a throwaway DB next). Evidence: `.context/arv2-onboarding-o3-acceptance/`.
- `2026-09-08-arv2-onboarding-o4-synthesis-split.md` — the O4 follow-up on `onboarding/o4-synthesis-split`: `onboarding-synthesis@v2` splits synthesis into one **ICP turn** plus one **persona turn per ICP** (identity `f"{run_id}:icp"` / `f"{run_id}:persona:{key}"`), the ICP turn on the `onboarding_icp` surface that *withholds* `exa_search_evidence` (and so drops the `audience-persona` skill), per-turn input selection with the core documents in the opening context via a `brand_knowledge_document` context card (L5 budget 262 144 B), the known-ICPs reuse rule, persona steps fanning out under the shared `onboarding_max_parallel_runs` cap, migration `ae4a5dfb3943`, registry digest `676ef758…`; the 7-item standing-rule checklist (all pass), the pre-existing base failures, the **`RecipeExecutor.execute` infinite-spin hazard** (execution substrate's to fix; contained here by a 1800 s `turn_hung` guard), and the owed live proof + possible `alembic merge`.
- `2026-09-08-arv2-onboarding-o5-knowledge-read-surface.md` — O5 landed on `onboarding/o5-knowledge-read-surface`: three workspace-scoped reads on `/frontend/v1/brand-context/{knowledge, knowledge/documents/{id}, onboarding/current}` (NOT the plan's `/api/v1/...`), the frontend wire model + knowledge repository, the page merge (`company, product, audience, proof, design` — Design keeps riding the brand-kit read), the Preview/Edit control removed page-wide, and the progressive-fill refresh hook; the two founder rulings (no status chip → servable documents only; edit removed everywhere, `Design.md` included), the brand-resolution order, and the deferred minors. Gates green except two **pre-existing** `tests/arv2` env-parity failures from base `33ab4fed1`; **acceptance NOT run — Task 7 is founder-triggered.** **Live acceptance 2026-09-08 (addendum): both O5 exit gates passed on the semarang stack (:8070/:3040) — real tree rendered, 220 polls / 30 tree re-reads during run 4 ($2.57); findings for O6 (system project visible in the sidebar; refresh hook arms on a live server render).**
- `2026-09-07-arv2-d2-display-module.md` — ARV2 D2 on `track-d2`: `clue_api/arv2/display/` (recipes,
  prompts, gather, runner, floor, blocks, evidence, page) + `scripts/generate_arv2_display.py`; the
  twelve decisions and the twelve execution rulings; the live exit gate and the three real Zafran
  pages ($0.038 for 17 sections, the unsafe-outside-restricted count `0`); the copy read-through
  notes; the close-out gate at baseline; D3/D4 follow-ups.
- `2026-09-07-arv2-onboarding-o1-o2-sdd-close-out.md` — O1 (substrate) + O2 (Exa Agent surface, templates, mappers) executed via SDD in two worktrees; branches to merge, the 7 rulings, not-this-lane triage list.
- `2026-09-07-arv2-onboarding-o2-exa-agent-surface.md` — O2 landed on `onboarding/o2-exa-agent-surface`: `ExaClient.agent_run` (create/poll/settle, failures returned not raised), the four §4 request templates, the `KnowledgeDocument` mappers; live Agent run $0.025 / 14 polls / ~65 s; final review wave fixed strict-mypy narrowing in the mappers, covered the `no_run_id` Agent create, and made the failure-note suffix explicit (mypy clean, 298 offline tests).
- `2026-09-07-arv2-onboarding-o1-substrate.md` — ARV2 onboarding O1 substrate landed: migration
  `0aa95f87eb49` (onboarding runs/steps, brand knowledge docs, project_product, product_set_selection
  gate), one head, smoke green; plus the throwaway-DB residue + `tests/db` isolation defect.
- `2026-09-07-no-old-lane-gate-may-block-new-lane.md` — **STANDING RULE, re-check at every stage:**
  no Client-KB / readiness / Stage-0-pin mechanism may block a new-lane (ARV2 / Track O) turn; only
  human-authority gates + the lenient claim shape gate exist; disposition table + 7-item checklist.
- `2026-09-07-product-catalog-contract-and-multi-product-ruling.md` — Exa catalog schema final,
  `ProductCatalogResearch@1`, rulings P1–P4 (a project targets a SET of products; one ICP per project).
- `2026-09-07-arv2-d1-migration-writer-and-answer-key.md` — ARV2 D1 on track-D: migration
  `65fb2128c904` (priority / outreach-safety / write-markers, owner columns, display_block,
  display_section_recipe, provider_call_ledger, account_activity_event, `Persona` gains
  `user`), the five leniency flags, the 38-row ARV2 field pack, the `LenientClaimWriter`, and
  the Zafran + ten-person answer key loaded as 294 real claims; four rulings, the plan's
  twelve decisions, the `.env`-sensitive suite caveat, and the D2/D3 follow-ups.
- `2026-09-07-arv2-r2-prereqs-seam1-probook-icp.md` — R2 prereqs wave 1: Seam 1 ratified (D9 open), Probook seeded, stand-in ICP + persona documents registered by the loader, product set v1, S7 content substance for review; AI Ark people endpoint still 402.
- `2026-09-07-arv2-r1-step0-and-client-dispatch.md` — ARV2 R1 on track-R: founder rulings (live tests only, native Gemini transcribe exception, keys), Step 0 wrapper/sinks/import guard landed (ee6fe1c94..076f0114a), provider_call_ledger spec, six client worktrees dispatched in parallel.
- `2026-08-19-live-research-queued-ui-and-fleet-failure.md` — timestamped browser, database, and
  worker evidence for the Insight Health ten-Account approval: why the frontend remains honestly
  queued, the unsealed-discovery-manifest Sumble refusal, the separate cancellation/closed-DB-
  connection process exit reproduced on restart, exact durable job state, and untouched Tunis.
- `2026-08-19-committee-discovery-blocker-inventory.md` — detailed permanent before/after ledger
  of every Account-research and committee-discovery blocker removed, exact-job-only prerequisite
  disabled, or historical threshold lowered through Account tier 4/source tier 4; also records the
  governance, spend, lineage, ambiguity, and no-new-UI controls deliberately retained.
- `2026-08-19-explicit-account-research-not-tier-gated.md` — founder ruling and implementation:
  explicit selected-Account research/committee discovery accepts high, low, tier 4, or absent
  signal tiers; exact R6 jobs bypass legacy scoring/must-have/tier checkpoints; a real paid Sumble
  browser run returned committee members and one inferred role; the backend now serves the role
  rationale without adding UI; 89 backend and 353 frontend tests plus all static/release and
  migration gates are green on the preserved D5 runtime.
- `2026-08-19-slice-d-make-check-baseline.md` — the Slice-D exit-gate full `make check` failure
  baseline: 68 failures A/B-proven byte-identical at the pre-lane-D base, decomposed into
  ambient-env / dirty-shared-DB / test-ordering / pilot-posture / 14 genuine inherited debts with
  exact signatures; lane D causes zero.
- `2026-08-19-slice-d-d3-agent-role-inference.md` — D3 adds the governed account-agent committee
  role write-back, exact member/evidence authority, honest roleless coverage, immutable account
  catalog v2 promotion, verification, review corrections, and the Fable/browser limitations;
  addendum: D3 controller-verified this session and D4's display-continuity bridge pins
  (agent-inferred member serves, roleless member stays discovered, toggle parity).
- `2026-08-16-part-iii-merge-into-platform-base.md` — merges the design Part-III branch into
  the platform base: profile-v24/recipe-v7 collisions re-versioned as v36/v16, the D8 run-event
  move reconciled with the recon constants, merged authority/registry counts (114/129), the
  a1c5b9842f0e Alembic join, and the two pre-existing reds recorded.
- `2026-08-16-stage0-icp-presentation-exa-preflight.md` — Slice 5 promotes bounded
  human-readable ICP synthesis in the normal assistant message alongside the approval gate,
  preflights confirmed Exa scope before any receipt/run write, repairs the active Recipe #0
  promotion to v13, and records focused backend/frontend/database verification and scope exclusions.
- `2026-08-16-stage0-discovery-configuration-v3.md` — implements Slice 4's provider-neutral
  discovery plan, optional scope-only human confirmation, immutable run receipt, Exa compilation,
  active v31/v18/v12 resources, and GPT-5.6 Terra high-reasoning baseline; records the live
  migration, strict-JSON, and restricted-surface defects found and fixed during review.
- `2026-08-16-stage0-confirmed-run-v2.md` — implements the trusted no-argument
  `start_confirmed_project_run@2` boundary directly over existing Stage-0 context, promotes the
  immutable v30/v17/v11 resources, and records the follow-up hardening for exact context bindings,
  advanced-run replay, mode-specific readiness identity, and guaranteed Recipe #1 attachment.
- `2026-08-16-stage0-confirmed-discovery-contract-freeze.md` — freezes the active confirmed-run
  correction: product context is a backend-derived receipt over five existing Stage-0 inputs,
  `start_confirmed_project_run@2` has no model-authored lineage, disabled budget controls are
  internal record-only/no-gate authority, and discovery configuration remains a separate contract.
- `2026-08-16-stage0-pin-and-client-target-fixes.md` — repairs the company-v2/product-v1 ICP
  synthesis compatibility pin and excludes the workspace's bound client from every FI-2 target
  account surface, with a green 103-test isolated-database matrix.
- `2026-08-16-integration-step6-verification.md` — records the complete post-merge verification
  ladder: static/resource/authority gates, merged functional matrices, fresh migration smoke,
  frontend release checks, and an exact unchanged 32-node backend quarantine match.
- `2026-08-16-integration-runtime-frontend-conflict-resolution.md` — completes the dependency-order
  runtime/frontend merge: unified gate authority, exact company/product Stage-0 scope, strict tool
  output validation, discriminated frontend decisions, and green backend/frontend verification.
- `2026-08-16-integration-migration-reconciliation.md` — joins the pilot and onboarding Alembic
  heads, installs the unified human-gate database authority, and records clean isolated migration
  and direct-SQL adversarial evidence.
- `2026-08-16-integration-immutable-resource-history.md` — preserves both resource lineages and
  promotes the combined Head-of-ABM v29, Stage-0 skill v16, and Recipe #0 v10.
- `2026-08-15-integration-field-policy.md` — freezes the distinct 9-field ICP, 11-field onboarding,
  12-field company-knowledge, and product-scoped field policies.
- `2026-08-15-integration-unified-human-gate-contract.md` — freezes the shared directive/ICP/product
  gate and answer contract before runtime and frontend conflict resolution.
- `2026-08-13-fi2-slice9b-selected-records-chat.md` — FI-2 Slice 9B adds capability-gated
  Account/Contact selection-to-chat handoff, opaque next-message-only composer state, accepted-only
  clearing, and a server-enforced exact selected-Account launch path under the budget-controls-off
  pilot contract; terminal verification is green and authenticated browser closeout is recorded as
  it completes.
- `2026-08-13-fi2-slice9a-bulk-actions.md` — FI-2 Slice 9A closes LF-ACCOUNT-005
  with capability-gated current-page selection, durable idempotent Account-to-project and Contact
  email actions, explicit numbered pagination, matching 40 px shell/footer alignment, and complete
  terminal plus authenticated-browser acceptance evidence.
- `2026-08-12-fi2-slice10-contact-email-enrichment.md` — FI-2 Slice 10 replaces the false
  timer-only Contact email cue with authenticated durable Exa + Sumble acquisition, preserves
  provider conflict and governance metadata without verified-email promotion, and records focused,
  migration, full-suite-baseline and authenticated browser acceptance evidence.
- `2026-08-12-fi2-slice10-sumble-email-probe.md` — disposable live Sumble contract probe proves
  v9 match-mode email selection, zero-credit async kickoff, terminal-poll charge boundary, and the
  separate MCP OAuth requirement; the follow-on Slice 10 implementation is recorded above.
- `2026-08-12-fi2-slice5-evidence.md` — FI-2 Slice 5 maps exact safe source URLs, evidence spans,
  confidence/freshness and protected artifact actions to display-approved Account/Contact claims;
  terminal and authenticated-browser closeout are recorded there as they complete.
- `2026-08-12-fi2-slice4-live-prose-formatting.md` — FI-2 Slice 4 implements typed current
  Account/Contact prose states, stable frontend enum labels and registry-described dynamic gaps;
  terminal/database gates plus authenticated browser-to-API-to-Postgres acceptance are complete,
  including every linked Contact shape and direct reload.
- `2026-08-12-fi2-slice3-contact-journey.md` — FI-2 Slice 3 closes LF-CONTACT-001 and
  LF-CONTACT-003 with one shared governed committee/addressability seam, named/withheld/unnamed and
  merged-link coverage, concise row/link accessibility names, full terminal gates, and an
  authenticated browser-to-API-to-Postgres acceptance run.
- `2026-08-12-fi2-slice2-account-recovery.md` — FI-2 Slice 2 closes LF-ACCOUNT-003
  with five typed recovery states, explicit workspace selection, request-correlated flag-off errors,
  safe expired-session reauthentication, pagination parity, focused/full gates, and an authenticated
  browser matrix that verifies every action and excludes runtime/internal error text.
- `2026-08-11-fi2-slice1-accounts-auth-cutover.md` — FI-2 Slice 1 removes every
  Accounts/Contacts runtime fixture and legacy workspace-header path, shares one authenticated
  server/BFF transport, renders the durable zero-account state, records focused/frontend/build/DB
  evidence, and closes signed-in desktop/mobile browser acceptance on the exact allowed origin.
- `2026-08-15-stage0-link-expansion-state-machine.md` — decouples durable page publication from
  recursive link expansion: fetched snapshots publish immediately, independently fenced expansion
  jobs retry/background-resume without provider refetch, fast wakes respect the DB deadline, the
  browser keeps polling after its timeout fallback, and a retained isolated 210-test DB gate plus
  frontend/static/migration verification is green. The later real browser/Scrapling/Luna canary
  auto-released at roughly 48 seconds and completed 52 snapshots with zero refetch, while exposing
  an unresolved crawl-run/page lock-order deadlock that inflated background completion to about ten
  minutes.
- `2026-08-15-stage0-fast-page-deferral.md` — fixes the 103.759-second eager-recon lease wait:
  clean unresolved fast pages now freeze out at the DB deadline and continue on the same
  background frontier, with authoritative v1/v2/replay regressions and a fresh 61-test DB gate;
  the no-override live Scrapling/browser rerun remains the release proof.
- `2026-08-15-production-context-s6.md` — S6 composition complete: governed interview/recon
  publication, OTLP-safe observability, body-free operator refs, real catalog/product selection and
  exact product-claim use, immutable v1-to-v2 turn pins, stream-race fencing, and an executable
  32-node broad quarantine; production release remains blocked by the 103.759-second fast phase.
- `2026-08-15-production-context-s5.md` — S5-A–F complete: separated company/product extraction,
  conservative catalog lineage, V2/product cards, trusted product reads, immutable company/product
  turn pins, real-fleet composition, and durable human-only product selection through the frontend.
- `2026-08-15-production-context-s50.md` — S5.0 decision gate complete: separate company/product
  knowledge scopes, paired selected-product card/tools, trusted-only product authority,
  `ClientKnowledgeCard@2` bounded catalog, coherent durable version-pair policy, executable state
  manifest, and S5-A–F runtime ownership without a premature cutover.
- `2026-08-15-production-context-s31.md` — S3.1 complete: immutable database-backed per-turn
  workspace/project/client/company-KB scope receipts, retry-stable vN semantics, frozen
  company-wide versus product-specific policy, production Stage-0 statement bindings, real
  AGENT_TURN/S4/checkpoint/finalization/replay/DSAR acceptance, and retained clean evidence.
- `2026-08-14-production-context-s4e.md` — S4-E and amended S4 complete: exact Client-KB result
  subject indexing, body-free stream projection, bounded turn/delegation/checkpoint DSAR closure,
  immutable injection-hardened profile v26/skill v13, no-resurrection replay, and retained clean
  119-test PostgreSQL acceptance evidence.
- `2026-08-14-production-context-s4c.md` — S4-C complete: unregistered frozen `@2` Client-KB
  discovery/inspection tools, paired production-artifact-only authority injection, typed durable
  JSON output/replay support, exact-version PostgreSQL/adversarial acceptance, and the S4-D
  production-registration handoff.
- `2026-08-14-production-context-s4a-s4b.md` — amended S4-A/B complete: marker/run-based exact
  version readers, retention-safe historical access, deterministic classification/pagination,
  and immutable provider/DB-free `@2` contract fixtures. S4-C through S4-E remain required.
- `2026-08-14-production-context-s4.md` — historical preliminary `@1` S4 implementation and
  production composition record. Reclassified by the amended S4-A–E roadmap; it is compatibility
  evidence and no longer means S4 as a whole is complete.
- `2026-08-14-production-context-s3.md` — S3 complete: production AGENT_TURN composition of the
  real L2 brand/confirmed product, paired account-wide Client-KB and active-project Stage-0 cards,
  exact per-turn version/receipt pins, pre-composition committed replay, product/account KB scope
  isolation, privacy-safe logs, and exhaustive isolated-DB/static verification.
- `2026-08-14-production-context-s2.md` — S2 complete: insert-once canonical workspace-client
  binding, conservative historical adoption, authoritative/transitional fleet composition,
  project inheritance, target-substitution refusal, migration/concurrency/tenancy evidence, and
  the exact S3 production-card composition handoff.
- `2026-08-14-stage0-crawl-recovery-backoff.md` — closes the C10 Scrapling recovery-wake follow-up:
  DB-clock delayed fleet requeue, earliest-lease/retry scheduling, bounded exponential fallback,
  ready-work non-starvation, migration/replay tests, and privacy-safe cadence logs.
- `2026-08-14-stage0-durable-official-site-crawl-c10.md` — C10 accepted: real Clerk/browser
  provisioning, sub-40-second Firecrawl/Scrapling authoritative release, same-frontier background,
  receipt/artifact/claim/replay reconciliation, live-discovered cutover/redirect/progress/category
  corrections, retained isolated evidence, and explicit provider-cost/recovery follow-ups.
- `2026-08-14-stage0-durable-official-site-crawl-c9.md` — C9 complete: executable 53-case/nine-
  crash matrix, recovered-result safety/receipt/provenance hardening, full retention reach, clean
  200-test isolated-DB gate, migration/frontend/static gates, and fully classified unrelated
  monolithic-suite baseline failures; C10 live cutover remains.
- `2026-08-14-stage0-durable-official-site-crawl-c8.md` — C8 complete: stable crawl/extraction
  events, rows-first setup/operator projection, full §17.4 metrics, privacy-safe logs, actionable
  fetch/extraction ambiguity reads, fenced recovery CLI/runbook, clean 164-test DB gate, complete
  frontend/static gates, and retained C7 row-only inspection evidence.
- `2026-08-14-stage0-durable-official-site-crawl-c7.md` — C7 complete: exact immutable-corpus
  reading, category-concurrent Luna/Terra extraction, durable response-before-parse operations,
  snapshot/URL/span grounding, provider-neutral claims, partial success, zero-spend cold replay,
  retained Insight Health live evidence, and the open C8/C10 lease-latency release gate.
- `2026-08-14-stage0-durable-official-site-crawl-c6.md` — C6 complete in default-off allowlisted
  shadow mode: one-run fast/background lifecycle, immutable checkpoints, fleet-owned onboarding
  recon/crawl work, phase-blocker recovery, reversible task-kind migration, 208-test focused gate,
  and retained Insight Health Firecrawl evidence with zero-call cold replay.
- `2026-08-14-stage0-durable-official-site-crawl-c5.md` — C5 complete: PostgreSQL-only bounded
  worker pool, cross-run global/host capacity, heartbeat/fencing, graceful stop, fast/background
  fairness, category quotas, replay-safe no-refetch depth expansion, bounded no-spend retries,
  multiprocess fault tests, and exact C6 production-composition handoff.
- `2026-08-14-stage0-durable-official-site-crawl-c4.md` — C4 complete: fenced
  prepared/dispatched/result/persistence attempts, PB-B2 content-addressed artifacts, URL-level
  provenance snapshots, persistence-only replay, paid-call reconciliation/quarantine, bounded
  privacy-safe receipts, DSAR reach, expanded crash matrix, and retained Firecrawl/Scrapling
  canary evidence.
- `2026-08-14-stage0-durable-official-site-crawl-c2.md` — C2 complete: versioned conservative
  URL identity, separate observation/edge/alias provenance, bounded sitemap/robots parsing,
  coordinator-owned SSRF/redirect/MIME/size/link safety, no-refetch shorter-path re-expansion,
  exhaustive adversarial fixtures, and retained isolated-DB evidence.
- `2026-08-14-stage0-durable-official-site-crawl-c1.md` — C1 complete: eight-table reversible
  PostgreSQL frontier/ledger, workspace/run structural isolation, generation-fenced claims and
  recovery, immutable verified checkpoints, provider-neutral `official_site` source, isolated-DB
  concurrency/migration evidence, and the exact C2 handoff.
- `2026-08-14-stage0-durable-official-site-crawl-c0.md` — C0 complete: frozen provider-neutral
  types/enums/tables/transitions/seams, PostgreSQL dispatch and reconciliation fencing,
  `official_site` source-key migration ruling, recursive-spike disposition, retained general
  Stage-0 prerequisites, provider-free fixtures, and the exact C1 handoff.
- `2026-08-14-stage0-durable-official-site-crawl-plan.md` — founder-approved implementation plan
  for a new provider-neutral Stage-0 crawler: PostgreSQL-only frontier/ledger, generation-fenced
  leases, conservative URL identity, provenance-preserving content dedupe, one fast/background
  run, single-page Firecrawl/Scrapling fetchers, paid-call recovery, C0–C10 gates, and live evidence.
- `2026-08-10-part2-d7-close.md` — **Part II D7 CLOSED:** one durable stream serves design —
  run_event/stream_token widened with generic subject_kind/subject_id (a02cbcb6e641),
  design_run_event dropped (eb9c5b963f40); lease-fenced emitter, self-contained terminals,
  single-use subject-bound tokens with workspace-from-token; editor on a fetch-stream client,
  wire contract byte-preserved; suite 548/9/0. D8 backlog inventoried.
- `2026-08-10-part2-d7a-subject-widening.md` / `…-d7b-stream-unification.md` — D7 round detail.
- `2026-08-10-part2-d6-close.md` — **Part II D6 CLOSED:** 49 design_* tools (classes in
  lumen_api/toolbelt/, clue_api lazy-registers; always-present, refusing when runtime off);
  one ToolInvoker write path for REST + agent over the shared A9/journal tables; no-bypass
  guard with equality-closed exemptions; scene CAS drop + 8 more correctness debts paid;
  generation ledger → Postgres (2711924d1e29); suite 543/9/0; registry 97/104.
- `2026-08-10-part2-d6a-toolbelt-foundation.md` / `…-d6b-documents-domain.md` /
  `…-d6c-assets-brand-personalization.md` — D6 round detail.
- `2026-08-09-part2-d5-close.md` — **Part II D5 CLOSED:** design turns + ingestion are leased
  fleet work (`design_job`, envelope-discriminated); daemon threads + orphan sweep gone;
  generation-fenced zombie writes; Postgres checkpointer with honest resume-as-restart;
  stranded-work reaper (re-offer once, then fail); shims + agent_runtime are real uv members
  (deepagents 0.6.12 treaty); O5 bridge survives by corrected ruling; suite 501/9/0.
- `2026-08-09-part2-d5a-durable-foundation.md` / `…-d5b-turns-on-the-fleet.md` /
  `…-d5c-ingestion-reaper.md` — D5 round detail (schema+CAS+envelopes; handler+checkpointer+API
  switch+kill-and-resume; ingestion+reaper+workspace debts).
- `2026-08-09-part2-d4-close.md` — **Part II D4 CLOSED:** every design asset byte durably on
  platform `clue_storage` (`{ws}/design/{sha}` keys, row-before-blob); Rust engine keeps a
  transient per-ws materialization cache (write-back + read-through); migration `13cd5078d697`
  (CHECK widened + `content_sha256` index); suite 501/9/0; two founder-ratification flags.
- `2026-08-09-part2-d4a-design-storage-seam.md` — D4 Round A detail: the `clue_design.storage`
  seam + `DesignBlobStore`; custom-component blobs + publish assets moved; sidecar dead; the
  CHECK-collision and shared-row media-type findings.
- `2026-08-09-part2-d4b-main-asset-store.md` — D4 Round B detail: engine cache demoted,
  `asset_custody.py` write-back/read-through, staged ingestion on storage keys, public route on
  the artifact table; the `tests/api` DB-pollution defect bisection; traps for later agents.
- `2026-08-08-part2-d3-concept-joins.md` — **Part II D3 done:** brand-kit brand_id +
  design_account account_entity_id stamped via resolve-or-create (clue_design/joins.py,
  interim scaffolding; Part III owns governed creation + NOT NULL + backfill); suite 490/0.
- `2026-08-08-part2-d24a-personalization-accounts.md` + `2026-08-08-part2-d24b-publishes-components.md`
  — **Part II D2.4 done (two Opus rounds):** personalization/accounts/batches (A) and
  publishes/components + O6b `/w/{ws}/p/…` public routes, bare routes deleted (B); document→
  account FK re-added; last cross-domain validation seam closed; migration `cf7dd82cf683`
  (account FK + workspace-local binding/instance/repair ids — founder nod pending); bridge
  fixed to private-engine-per-call (concurrent calls); design suite 487/0. Remaining: D2.5.
- `2026-08-08-part2-d23-brand-assets-ingestion.md` — **Part II D2.3 done:** brand kits/compat,
  asset registry/descriptions, ingestion jobs on Postgres; scene-asset promotion in-transaction
  (D2.2 seam closed); migration `cf4f80537c8e` (content-derived asset ids + client-supplied
  snapshot ids → workspace-local PKs). **Incident:** a D2.3 agent ran `git reset` to D2.1
  despite the no-git rule — orphaned the D2.2 commit + clobbered fixed tests/docs; recovered
  via reflog + `git checkout acd10f8e --`. Future agent briefs: no git, verify file states in
  review. (Phase-B detail note: `2026-08-08-part2-d23b-ingestion-descriptions.md`.)
- `2026-08-08-part2-d22-documents-history-port.md` — **Part II D2.2 done:** documents+history
  on Postgres behind `HybridRepository` (scene CAS added; legacy asset-metadata 410s per O3);
  migration `7a9881f9717a` — workspace-local PKs extended to all client-supplied/content-hash
  id namespaces (**needs founder ratification**), account FK deferred to D2.4; design suite
  487/0 green after harness adaptation + merge-fallout repairs (fixtures, npm). jsonb does NOT
  preserve object key order — never select nodes by dict position. Opus-implements/Fable-reviews
  process now binding.
- `2026-08-07-part2-d21-dal-foundation.md` — **Part II D2.1 done:** `lumen-api` packaged +
  explicit uv-workspace member (agent-runtime deps deliberately excluded; dead `pypdf` pin
  dropped over a real lockfile conflict; py_lumen_* stay PYTHONPATH until Step-2);
  `clue_design` gains errors + parent-row-lock sequence allocators (O5 one-transaction rule
  binding); 10/10 design DB tests incl. an observed lock-blocking concurrency proof.
- `2026-08-07-part2-d1-design-schema.md` — **Part II D1 done:** six `design_*` migrations off
  `c6d84aa84b79` (head `e79f192828b1`), 11 package-local enums + parity, immutability triggers,
  structural tenancy; db-smoke + 6/6 design tests green. Env gotcha: localhost:5432 = Homebrew
  PG17, NOT the docker container. Pre-existing DB-suite failures (waterfall et al.) proven
  D1-independent by A/B. Next: D2 after O6b ratification.
- `2026-08-07-part2-o1-o6-ratified.md` — **O1–O6 RATIFIED (founder); D1 unblocked.** Key
  refinements: `design_brand_kit` promoted to THE platform versioned brand-kit payload (brand
  studio vision); `asset_descriptions` ported with full behavior; O5 atomicity rule binding;
  fleet-for-design-deepagent uncertain but concurrent multi-session runs binding; O6 slugs
  workspace-local with O6b (interim `/p/{slug}` rule) open for D2; append-only design history
  is a preserved principle — no destructive compaction ever.
- `2026-08-07-part2-d0-preflight.md` — **Part II slice D0 done:** contract doc
  `docs/specs/PD-part2-design-substrate.md` (slice map, 22-table `design_*` map, rules, open
  decisions O1–O6 — **unratified, gate D1**); `subsystems/design/clue_design` scaffold under all
  gates incl. new Rule-S4 contract; clue-design logging-guard carve-out. Pre-existing red found:
  23-file ruff-format drift at `origin/main` fails `make lint` — ruling pending.
- `2026-08-07-alembic-single-head-c6d84aa84b79.md` — **Alembic has ONE head: `c6d84aa84b79`**;
  all new (incl. Part-II `design_*`) migrations chain off it. A 4-head report was false (it
  counted Phase-C branch tips already joined by `fc1f3d22a167`). Verify with
  `uv run alembic heads`, never by eyeballing the versions dir.
- `2026-08-07-design-subsystem-monorepo-merge.md` — Design-integration **Part I / Step 1** done:
  `clue-design`/*havana* merged into `subsystems/clue-design/` (full history preserved; on
  `origin/main` via PR #40; design-only ancestry = 2nd parent of `3ab4a750`), excluded from the
  uv workspace + ruff pending Step-2 hygiene. Parts II–IV (substrate / agent / surface) not
  started. Authoritative plan: `docs/specs/design-integration-master-plan.md`.
- `2026-08-06-m8d-r9-parallel-execution.md` — R9 accepted: exact-wave dependency checks,
  atomic budget/provider admission, concurrent Exa/Sumble execution, partial-result joining,
  callback-race-safe composite waits, cold-resume/crash replay, DSAR, and isolated-DB evidence.
- `2026-08-06-m8d-r0-r4-adversarial-fixes.md` — closes every reviewed R0-R4 P1/P2:
  exact field/source authority, full legacy quarantine, globally scoped checkpoints, immutable
  state/finalization history, provider-neutral causation/results, multi-contact projections,
  bounded follow-up context, lossless UTF-8 reads, checkpoint-aware DSAR, and fresh-DB gates.
- `2026-08-06-m8d-r4-governed-tools-persisted-results.md` — R4 accepted: exact semantic tool
  authority, provider-operation causation before dispatch, complete lossless persisted results,
  Exa contact composition, replay/follow-up lineage, DSAR reach, isolated-DB regression evidence,
  and the retained R5/R9/R10 boundaries.
- `2026-08-05-m8c-v0-offline-database-acceptance.md` — M8C V0 complete mechanically: frozen
  55-gate C0–C7 matrix, prerequisite-populated synthetic database and zero-call fresh replay,
  provider-id/count isolation repairs, clean 3,412-test full suite, migration/static gates,
  categorized failure ledger, and the separate V1 live-provider boundary.
- `2026-08-05-m8c-c5-selected-contact-channel-enrichment.md` — C5 mechanically complete:
  exact selected-contact/channel authority, Exa one-person acquisition, independent validation,
  atomic split spend, governed identity promotion, replay, DSAR/retention, clean database
  verification, and the separately authorized paid-canary/C6 handoff.
- `2026-08-05-m8c-c4-exa-contact-acquisition-materialization.md` — C4 complete mechanically:
  transaction-free exact-contact Exa dispatch, immutable snapshots and honest one-time cost
  settlement, exact-target replay through governed `fill_contact_field`, crash/same-name/malformed
  defenses, clean database verification, and the separately authorized live-canary/C5-C6 handoff.
- `2026-08-05-m8c-c3-contact-exa-compiler.md` — C3 complete mechanically: exact-contact/employer
  Exa Deep compiler, registry/source-plan authority, directional structured output, fail-closed
  same-name parser, content-addressed fixtures, clean full-suite verification, and the C4 handoff.
- `2026-08-05-m8c-c2-atomic-lineage-remediation.md` — closes both audited C2 blockers:
  the public reserve API solely owns semantic reuse serialization/capacity reservation, every
  Exa claim requires exact operation/snapshot/request/result-artifact lineage, provider doubles
  use honest fixture source identities, and clean full-suite/migration verification is green.
- `2026-08-05-m8c-c1-selection-lineage-remediation.md` — closes both audited C1 findings:
  bounded strong-first People/Teams union selection preserves organization-map representation;
  typed immutable claim provenance plus exact database-enforced Sumble operation/snapshot/
  artifact/account/contact lineage; clean full-suite and migration-smoke verification.
- `2026-08-04-m8b-v0-offline-database-acceptance.md` — V0 complete mechanically: frozen
  32-case fault manifest, Sumble response-before-normalization durability and charged-drift
  quarantine, disposable migration/concurrency/fresh-process inspection, clean 3,337-test suite,
  static/import/one-head gates, and the separately authorized V1 live boundary.
- `2026-08-04-m8b-o3-main-agent-steering.md` — O3 complete mechanically: non-linear Head-of-ABM
  account-deep steering, exact current directive/launch/account L3 context, truthful governed tool
  descriptions, pre-launch research-specialist behavior, scripted conversation gates, and
  provider-free real-Postgres verification; V0/V1 remain.
- `2026-08-04-m8b-o2-account-deep-composition.md` — O2 complete mechanically: explicit immutable
  exact-set launch after the conversational/tier pause, account budget/pin propagation, canonical
  Exa preparation and snapshot replay, durable S1/A2-backed no-reveal Sumble committee inputs,
  existing fleet/orchestrator composition, real-Postgres acceptance, and O3/V0/live handoff.
- `2026-08-04-m8b-e0-a2-integration.md` — merged the complete E0 request/response branch into the
  A2 account-profiling integration branch; reconciled roadmap state, isolated the negative Exa
  credential test from local environment configuration, and verified the combined E0/A2/deep/
  Sumble seams without provider traffic.
- `2026-08-04-m8b-a2-research-directive.md` — M8B A2 plus critical-review remediation:
  immutable research direction, exact sealed membership and production launch pins, canonical
  source authority, trusted human confirmation receipts, complete previews, explicit memory
  outcomes, bounded context, project-artifact erasure, and provider-free verification.
- `2026-07-28-phase-c7-8-closeout.md` — C7.8 and C7 complete: 18-case executable
  adversarial matrix, 10-surface DSAR matrix, breadth-batched/capped derivation reads, six
  independent default-off activation controls, operations/runbook/status closeout, clean full
  verification, and the single remaining C8 legacy-write hard-fence handoff.
- `2026-07-28-phase-c7-7-product-serving.md` — C7.7 complete: exact reference-only tools,
  account/contact and legacy-alias HTTP surfaces, body-free status projections, transactional
  canonical/SSE event aggregation, live C6 fetch authority, clean full verification, and C7.8
  adversarial/DSAR/performance closeout.
- `2026-07-28-phase-c7-6-production-committee-handoff.md` — C7.6 complete: one run/product-bound
  governed contact resolver, production C7/M12 adapters, exact product lineage, real
  retention-wrapped materialize/outbox HANDOFF, run-keyed composition isolation, adversarial
  eligibility/crash coverage, and the C7.7 serving cutover.
- `2026-07-28-phase-c7-5-governed-recheck.md` — C7.5 complete: strict additive re-check contract,
  immutable reference-only change reports/events, deterministic crash replay, reverse-reference
  section staleness, governed tool delegation, full isolated verification, and the C7.6 handoff.
- `2026-07-28-phase-c7-4-reference-snapshots-evidence-access.md` — C7.4 complete: append-only
  body-free snapshot receipts, current-policy live resolution, exact-scope evidence actions,
  legacy handoff subject indexing/purge/no-resurrection, full isolated verification, and the
  bounded C7.6/C7.7 payload cutover.
- `2026-07-27-phase-c7-3-research-view-composition.md` — C7.3 complete: injected owner
  seams, deterministic account/contact composition, nine-block reference adapter, adversarial
  state coverage, isolated full-suite verification, and the exact C7.4 handoff.
- `2026-07-27-phase-c7-2-derivation-entailment.md` — C7.2 complete: derived claim flavor,
  append-only ordered support graph and entailment ledger, strict no-rationale judge, conservative
  API-root promotion, bounded live dependency invalidation, transitive DSAR reachability,
  migration/full-suite verification, and the exact C7.3 handoff.
- `2026-07-27-phase-c7-1-prerequisite-hardening.md` — C7.1 complete: shared equality
  consumer parity, fail-closed retention-aware live selection, one-way faithfulness-rationale
  DSAR redaction, evidence-access authorization/service seams, product-exact score claims, optional
  registered contact class, isolated-DB migration smoke, and the exact C7.2 handoff.
- `2026-07-27-phase-c7-0-contract-fixtures.md` — C7.0 complete: frozen account/contact
  research-view contracts and protocols, executable source-species/nine-block ownership map,
  sanitized frontend/adversarial fixture manifests, fail-closed contract tests, full tracked-scope
  verification, and the exact C7.1 boundary.
- `2026-07-27-phase-c7-planning.md` — C7 planning checkpoint on
  `platform/c7-research-views`: founder-ratified dossier-as-structured-research-view ruling,
  account/contact frontend contract, derivation/entailment and reference-only snapshot decisions,
  C8 prerequisite placement, C7.0–C7.8 slices, verification gates, and next implementation entry.
- `2026-07-26-phase-c6-8-production-closeout.md` — C6.8 and C6 complete: prepared account
  turn composed in the existing DEEP slot; immutable one-owner routing; default-off flags;
  body-free read API; cache/context/workspace/delegation/finalization telemetry; secure cold
  workspace resume; retention cleanup; canary comparator; full operational runbook, verification,
  and C7.0 handoff.
- `2026-07-26-phase-c6-7-account-research-agent.md` — C6.7 complete: governed per-account
  deepagent inside the existing fleet slot; one replay-safe C5 gap-research operation; sole C1
  evaluator ownership with append-only non-authoritative advice; terminal-coverage finalization
  guard; no double spend; full DB-enabled verification; and C6.8 handoff.
- `2026-07-26-phase-c6-6-specialist-subagents.md` — C6.6 complete: governed fresh-wake research,
  content-drafter, and reviewer children; exact task/artifact/ref transfer; isolated execution and
  empty-history context; role-specific resources, tools, budgets, outputs, durable receipts; skill
  authoring guide; full DB-enabled verification; and C6.7 handoff.
- `2026-07-26-phase-c6-5-head-of-abm-stage0.md` — C6.5 complete: real Head-of-ABM
  Stage-0 deepagent, additive exact resources, exhaustive unavailable-capability map, nine-tool
  allowlist, progressive Stage-0 skill, C5/Recipe-0 pin parity, replay-certified proposal and
  ingestion paths, human readiness/confirmation authority, full verification, and C6.6 handoff.
- `2026-07-26-phase-c6-4-governed-agent-runtime.md` — C6.4 complete: whole-proposal C5 compiler,
  exact governed framework tools, real deepagents loop, async-Postgres checkpoints, artifact-backed
  model receipts, durable fresh-wake delegation, honest finalization authority, complete crash
  matrix, full DB-enabled verification, and the C6.5 handoff.
- `2026-07-26-phase-c6-3-durable-turns-context-replay.md` — C6.3 complete: reversible normalized
  durable turn/context/history/model/finalization receipts, deterministic budgeted L1–L7 context,
  append-only artifact-backed history, body-free cold replay, subject-indexed DSAR and workspace
  purge, no-resurrection tombstones, full DB-enabled verification, and the C6.4 handoff.
- `2026-07-26-phase-c6-2-catalogs-profiles-model.md` — C6.2 complete: immutable V1 folder
  resources, strict provider-neutral catalogs, four active role profiles plus planned
  account-research, exact effective/delegated tool authority, progressive skill disclosure,
  governed OpenRouter tool-calling/fallback/streaming attribution, deterministic model fake,
  full verification, and the C6.3 handoff.
- `2026-07-26-phase-c6-0-contract-freeze.md` — C6.0 complete: strict agent/resource/plan/context/
  delegation/finalization contracts and injected ports; exact deepagents/model dependencies; real
  fresh-wake, OpenRouter tool-call, async-Postgres resume, artifact-workspace, and honest-finalize
  spikes; 32-tool replay/authority audit; stock-filesystem rejection; C6.1 handoff.
- `2026-07-26-phase-c6-planning.md` — binding C6 child spec and cross-session implementation plan:
  real Doc-A deepagent; external per-execution `virtual_mode=True` workspace; relative paths only;
  no application code or execution tools in the runtime workspace; folder-backed prompts, skills,
  and profiles; C5 durability; C1 evaluator ownership; C6.0–C6.8 sequencing and gates.
- `2026-07-25-phase-c5-6-recipe1-cutover.md` — C5.6 and C5 complete: promoted executable Recipe #1
  phase graph, lineage-validated Stage-0 pre-satisfaction, feature-gated new-run routing with
  legacy fallback, retryable external waits, full historical views, canonical parity fingerprints,
  scripts 01–06 locality repair, complete repository verification, and the C6 handoff.
- `2026-07-25-phase-c5-5-supervisor-controls.md` — C5.5 implemented: run-scoped source telemetry,
  deterministic aggregate supervision, bounded durable diagnosis, replay-safe enforced controls,
  canary-gated deep execution, exact ICP-policy validation, full repository verification, and the
  C5.6 cutover handoff.
- `2026-07-25-phase-c5-5-repository-verification.md` — C5.5 repository verification checkpoint:
  clean DB-enabled full suite (2,432 passed, 20 skipped), lint/type/import-contract gates,
  migration head→base→head smoke, the required project-run aggregate test correction, and the
  untracked local skill-directory lint caveat.
- `2026-07-25-phase-c5-4-recipe0-migration.md` — C5.4 implemented: promoted executable Recipe #0
  v2, bounded durable Stage-0 interaction children, exact resource pins, direct-vs-durable parity,
  four-boundary crash recovery, tombstone/memory/locality enforcement, and the honest C5.5/C5.6
  handoff.
- `2026-07-24-phase-c5-3-durable-executor.md` — C5.3 implemented: generic generated-lease fleet,
  deterministic crash-resumable recipe executor, bounded maps and human gates, typed/audited
  controls, single-owner routing, real SIGKILL recovery evidence, full verification, and C5.4
  handoff.
- `2026-07-24-phase-c5-2-recipes-compatibility.md` — C5.2 implemented: append-only immutable
  recipe lifecycle, closed typed graph/bindings, exact all-error compatibility loader, API-root
  production adapters, promoted non-runnable Recipe-#0/#1 identity seeds, full verification, and
  the C5.3 handoff.
- `2026-07-24-phase-c5-1-execution-journal.md` — C5.1 implemented: full append-only execution
  schema, journal/cursor/outbox transaction, governed parameter artifacts and erasure tombstones,
  mandatory production ToolInvoker, durable replay/retry/blocking, read views, verification, and
  the C5.2 handoff.
- `2026-07-24-phase-c5-0-contract-freeze.md` — C5.0 implemented: exact-version descriptors and
  recipe steps, strict typed outputs, stable operation identities, executable Recipe-#0/#1 replay
  audit, honest provider/recon residuals, verification, and the C5.1 handoff.
- `2026-07-24-phase-c1-c3-integration.md` — C1–C3 integration checkpoint: central 24-tool and
  projection aggregation, cross-lane proposal/ingestion wiring, authoritative contact governance,
  exact-source erasure, Alembic merge head, spend-path inventory, verification, and C4 handoff.
- `2026-07-24-phase-c3-ingestion.md` — C3 implementation state: durable ingestion jobs/segments,
  stable document adapters, governed claim routing, tool/projection surfaces, concurrency and DSAR
  hardening, verification evidence, and integration-owned follow-ups.
- `2026-07-24-phase-c-c1-coverage-goal-judge.md` — C1 implementation handoff:
  bounded coverage attempts, append-only attempt/decision ledgers, goal judge,
  gap-research tool/projections, waterfall observation hook, and verification.
- `2026-07-24-phase-c-c0-contract-freeze.md` — C0 executed: exact C1–C4 shared types,
  schema/tool/projection ownership, fixtures, governance-prerequisite disposition, safe parallel
  wave, integration order, and later Phase-C concurrency ruling.
- `2026-07-24-phase-c-plan.md` — ratified Phase C parent plan: Stage-0 product model, C0–C8
  sequencing, C1–C4 worktree treaty, fixed decisions, prerequisites, and the required next-session
  contract freeze before implementation.
- `2026-06-25-m10-m11-m12-integration-plan.md` — how to integrate the M10/M11/M12 parallel worktrees: data-flow sequencing (M12 last), the as-yet-unbuilt VERIFICATION/HANDOFF runtime spine, the alembic 2-head merge, and the most-important invariant (tombstone-before-merge-read).
- `2026-06-26-m13-parallelisation.md` — the M13 Wave-1 (M13.1/M13.2/M13.4 parallel) + Wave-2 (M13.3) plan, the 4 load-bearing decisions, and the per-workspace briefs.
- `2026-06-26-m134-observability-surface.md` — M13.4 (cost & progress surface) complete: the read-only `ObservabilitySurface`, its api-root wiring, the `cost_estimate` migration, the coverage/verification-health/pre-run-estimate decisions, and the integration follow-ups.

- **2026-08-01 — Stage-0 acceptance run PASSED** (`2026-08-01-stage0-acceptance-run.md`): structured-output repair plan + F6/F7/F8 landed; live Terra interview → grounded confirmed ICP; entailment-strictness product finding; Sumble canary is next.

- **2026-08-10 — Part II D8 CLOSED; Part II COMPLETE (D0–D8)** (`2026-08-10-part2-d8-close.md`): outbox consolidation (one DAL owner + `clue_core.run_event` contract-delta), dead liveness net deleted, retention (token sweep ON / design pruner OFF with in-code floors), Part-II gate machine-checked end to end, DSAR **assessed not wired** (`docs/specs/PD-D8-dsar-assessment.md`); founder items: pruner enablement + the standing D2.2/D4 flags.

- **2026-09-02 — WOFF2 brand fonts: investigation + option A plan (NOT executed)** (`2026-09-02-woff2-font-investigation-and-plan.md`): the SVG refusal is the container check, not the license gate (0 restricted fsType bits in stored fonts; 94% of files are WOFF2); three sfnt-only consumers (Rust embedder, CanvasKit, FreeType/Linux); plan `docs/superpowers/plans/2026-09-02-woff2-font-decode-at-ingestion.md` — decode at `CoreClient.ingest_asset`, web lane re-encodes, backfill script, brotli must be declared.

- **2026-09-02 — WOFF2 fonts decoded at ingestion (option A), backfill applied on colombo dev** (`2026-09-02-woff2-decode-at-ingestion.md`): fonts now stored as sfnt (`CoreClient.ingest_asset` decodes WOFF/WOFF2; web lane re-encodes at export); dev backfill `294 decoded, 142 missing blobs`; live proof — Apollo doc's canonical SVG embeds Season Mix + Söhne as `font/ttf` with zero font diagnostics; Task 4b checkpoint excuse stays until every environment is backfilled.

- **2026-09-03 — Agent-working chip: visible form of the scene editor lock** (`2026-09-03-agent-working-chip.md`): "Designing. Please wait to edit." chip with dot-grid pulse + text shimmer, top-left of the scene stage while `agentRunLock.locked`; zero-dependency CSS; live-proven on the thread route. FINDING: the standalone artifact route (`editor-surface.tsx`) passes no lock at all — founder decision pending.

- **2026-09-03 — Standalone artifact route now honours the editor lock** (`2026-09-03-standalone-artifact-lock.md`): `GET /documents/{id}/agent-run` (the 409's own predicate + current_version) polled every 4 s by `EditorSurface`; locks session/inspector/gestures/Edit, shows the chip, reloads on version moves. Live-proven on the Apollo doc. Test suites left 19 `ws_test_*` design jobs in the shared queue again (worker restarted).

- **2026-09-04 — Apollo dry run: seven editor defects, root causes, roadmap** (`2026-09-04-editor-quality-dry-run.md`): kit line-height 4.5 = px/16 parser bug; bold/italic dead = single-face kit, variable fonts never instanced; CTA unselectable = deepest-leaf hit + no hover/walk-up; box≠paint = layout-box hit-test; pageless streaming = pageId picked once at load; page-before-assets unordered. Roadmap `docs/superpowers/plans/2026-09-04-editor-quality-roadmap.md` (order: ingestion → fresh doc → selection ladder → text bounds last; inspector controls gated on a founder icon preview).

- **2026-09-04 — Plan 1 shipped: type units + instanced faces + honest Bold/Italic** (`2026-09-04-plan1-type-units-and-faces.md`): parser line-height/letter-spacing are element-relative (px/16 bug); LUMI0233 normalizer guard; variable fonts instanced to 400/500/600/700 static kit faces at ingestion (LUMI0234/0235); `scripts/rederive_kit_type_units.py` backfill (dry-run default, --repin-documents); editor Bold/Italic disable with a reason when the kit has no face. Live-proven on the Apollo ad (kit v3/v4; editor reads `scene.meta.brand_kit`, so rebinding needs the attach route).

- **2026-09-04 — Plan 2 shipped: page first + pre-spend guard + canvas on the first streamed batch** (`2026-09-04-plan2-page-first-and-first-batch.md`): asset tools refuse on a pageless scene (`scene.page_required`) before any spend; page-first rule in the director/author prompts and the LinkedIn ad skill; the canvas draws the page of the scene it streams. Live proof exposed a second blocker — ledgered-but-unstreamed ops made the frontend cursor dirty — fixed at the `record()` chokepoint (frames carry every ledger op since the last frame). Proven on a fresh Apollo/Brex ad: artboard on the first frame at document version 0.

- **2026-09-04 — Plan 3 shipped: selection ladder** (`2026-09-04-plan3-selection-ladder.md`): pure `scene-selection-ladder.ts` (button-first hit, walk-up to the nearest representable ancestor, hover target, Escape effect, breadcrumb ancestry); double-click on a button edits its label; canvas wiring (Alt-click / same-spot second click / Escape walk up; hover outline as `SelectionChrome variant="hover"`). Live-proven on the Brex ad; the Apollo CTA is unreachable because it overflows its clipped column (engine hit-tests layout boxes — Plan 4). Inspector breadcrumb declined by the founder after a preview (Layers covers ancestry). Layers tree now indents by real depth (the flat 16px CSS was the "depth cap").
- 2026-09-04-web-editor-page-section-and-mint-removal.md — Page section two-group repair, mint-green/fixture palette removal, canvas swatch hydration
- `2026-09-08-arv2-r2-account-agent.md` — R2 BUILT + live acceptance passed (Probook 85 / Zafran 104 claims); rulings, observations and R2-close follow-ups
- `2026-09-09-arv2-r3-person-agent.md` — **R3 close-out**: the committee step and the person agent BUILT, live acceptance **partial by ruling** (six people end to end on the fixed code; Zafran's fan-out proven, its four person jobs dequeued). Commits, all fourteen rulings, the live defects (L1 employer lock, L2 off-target insight, C1b phone scan) and the read-surface walk (W1–W4), the acceptance numbers and parallelism measurement, and the follow-ups (facet-text recall grader; account finalize candidate dedupe; the loader's `core.work_email` rows; per-process concurrency is a fleet change; legacy-only committees now read empty by design; the not-run people and how to re-offer them). Evidence `.context/arv2-r3-acceptance/acceptance.md`; lane docs `platform/api/clue_api/arv2/README.md` § R3.
- `2026-09-10-arv2-r4-websets-experiment.md` — R4 discovery experiment: Exa Websets vs `/search` on the v3 ICP; Websets 14/25 strict passes vs search 2/4; 5 Websets verdict errors caught by our $0.007 stage probe; cost per qualified company and the R4 design it argues for.
- `2026-09-10-arv2-r4-discovery.md` — **R4 close-out**: verified account discovery BUILT on `track-r4` (`fefddcbfb` → this commit), **live exit gate owed** (`.context/arv2-r4-acceptance/`). Exa Websets finds the long list, Exa Answer verifies every ICP hard gate with a quote and a source, three code guards (quote-on-page, right-company, window arithmetic) overturn what the model got wrong; fleet kind `arv2_discovery` + migration `2cd622be2da0`, the store/brief/verifier/launch/driver modules, the CLI, the approval stamp on the existing "Add to project" bulk action, and the Head-of-ABM grant (`head-of-abm@v45` / `stage0-interview@v22` §7b / `recipe0-stage0@23`). All twenty rulings (§9's fourteen plus the six taken during SDD), the **7/7 standing-rule checklist**, both gate runs (offline 1155 passed / DSN-only 1334 passed, one design-profile red plus two lane-DB answer-key reds), the pre-existing reds left alone, and the follow-ups (Websets exclusion import; worker scheduling; the chat gate after the target-accounts tab; the recall angles; an `exa-pro` comparison; splitting `unknown_criteria_gate_key`). Lane docs `platform/api/clue_api/arv2/README.md` § R4.
- `2026-09-11-san-salvador-lane-stack.md` — the lane's dev stack for manual ARV2 testing: `./scripts/dev_stack_san_salvador.sh up|down|status` (runbook ports 3020/8010/8020/8030, DB `clue_san-salvador`, 4 workers × 3 slots, logs `/tmp/san-salvador_*.log`); `dev_stack.sh` gained `DEV_STACK_*` knobs + a worker-launch stagger; istanbul/colombo/semarang stacks stopped 2026-09-11 (same ports — `down` one before `up` the other); follow-up: worker-boot field-registry seeding races on `field_definition_pkey` under concurrent starts.
- `docs/superpowers/plans/2026-09-11-arv2-defect-and-remaining-work-ledger.md` — the ARV2 defect + remaining-work ledger (O6, 9d, R4, the 2026-09-11 stack bring-up): live defects A1–A9 (onboarding fan-out duplicate step → run `failed`; registry seed race; Welcome flow drives the old recon; provisioning/recon flag coupling; no start surface; Clerk token facts; env parity), owed gates B1–B4, R4 follow-ups C, O6/9d follow-ups D, pre-existing reds E, frontend items F, old-pipeline retirement order G. Update statuses in place; never delete rows.
- `2026-09-12-project-context-files.md` — plan 1 of the context/ICP-authoring set: `inputs/project/status.md` + `decisions.md`, the per-turn `agent_turn_project_files` pin, `ProjectFilesIndexCard@1`; live proof owed.
- `2026-09-12-icp-authoring.md` — plan 2 of the same set: the Head of ABM can **author an ICP** (`author_icp_document@1`, born `proposed`, brand or project scope, lineage via `derived_from`) and **request personas** (`request_persona_synthesis@1` → a personas-only `onboarding_run`). Migration `b953bf11e2a9` gives `brand_knowledge_document` a `project_id` + `derived_from_document_id` and a scope-aware unique index; the reader rule is brand-readers-see-brand-rows / project-readers-union-and-project-wins; project documents materialize under `inputs/project/` and list in `status.md`. Grant: skill v23 (§5b/§5c), profile `head-of-abm@v46`, recipe v24. 7/7 standing-rule checklist, no new flag; **live walk owed** (SQL + checklist in the note).
- `2026-09-12-project-plan-document.md` — plan 3 of the same set: the Head of ABM **writes the project's plan** (`write_project_document@1` → `project/plan.md` as a `project-plan` knowledge document, one immutable version per save guarded by the version it read), and a human edits it through the project-documents HTTP surface (`GET/GET/PUT /frontend/v1/projects/{id}/documents[/{documentId}]`, `expected_revision`, `user_edit` provenance, 404/409/422 refusals). Grant: skill v24 §6b, profile `head-of-abm@v47`, recipe v25 (promoted on the lane DB). Rulings I–L; the **Plan tab, editor, card click-through and gallery document cards are deferred** to `docs/superpowers/plans/2026-09-12-plan-tab-frontend.md` (R12); **live walk owed** (SQL + curl checklist in the note).
- `2026-09-13-head-of-abm-read-tools.md` — plan 4 of the same set: the Head of ABM **reads before it speaks** — `read_project_accounts@1` (the project's accounts with each one's research status and a `refreshing` flag), `read_account_research@1` (the account's written overview in the page's own order, or its claims with evidence), `read_discovery_run@1` (the latest or a named run with its tallies and candidates). All three effect-free, ambient-workspace, and typed-refusal-on-absence (`project_not_found` / `account_not_found` / `overview_not_written` / `account_not_researched` / `no_discovery_run` / `discovery_run_not_found` / `arv2_reads_not_composed`); registered with **no flag**. Grant: skill v25 §7c, profile `head-of-abm@v48`, recipe v26 (promoted on the lane DB). Rulings M (no lineage; any future lineage re-checks `workspace_id`), N (the skill summary rewritten, not appended), O (`total` counts what the listing can show); **live walk owed** (checklist + journal SQL in the note).
- `2026-09-14-lane1-e2e-walk.md` — Lane 1 end-to-end walk on the rebased stack (v57/recipe 28): 7/8 pass; findings F1–F7, the real one F6 (the executor spins on a `node.blocked` child after the gate decides and wedges the thread); Redis unprovisioned for this lane; manual recovery steps recorded.
- `2026-09-13-live-walk-findings-and-workspace-reorg.md` — plan 4 in anger: the "what was researched about Arthur Direct Care?" turn died on five causes (`read_discovery_run` output-contract bug on the `pass` alias; the claims read overflows the 16 KiB governed receipt; `overview_not_written` is honest because overviews render on first page view; a guessed `field_prefix`; the per-turn failure budget of 3 spent by a parallel fan-out). The workspace as it really is (one directory per turn, ids derived by uuid5, isolation per workspace) and the founder's reorganisation rulings W1–W11 → `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` (four-level workspace, project library as a materialized view, one save tool + document skills, paged/spilled reads, personas by the Head of ABM). **Hotfix landed 2026-09-13 night (lane-1 plan 0, `0b1975628..423e5bb40`, profile v50 / skill v27) and proven live on the lane stack — the paged Prevea Health read and the discovery read both complete; see the note's plan-0 section.** **Plan 1 landed the same night (`24650d9f2..5e2557a73`, profile v51 / skill v28, migration `5e78522ddf48`): one persistent workspace directory per chat thread with `scratch/` and `reads/`, mounts on the backend, per-turn rewrite of the platform trees, outputs snapshotted then emptied, retention by thread — proven live with a two-turn notebook walk; see the note's plan-1 section.** **Plan 2 landed 2026-09-14 (`3b236c669..670c76e3d`, profile v53 / skill v30 / prompt v9): the brand library once per knowledge version mounted read-only as `brand/`, the project library (status, decisions, one version per document, artifact index) compiled from rows and mounted as `project/`, the turn pins the library manifest and replays from the pinned set, writers and DSAR refresh it — proven live with reads of `project/status.md` and `brand/index.json`; see the note's plan-2 section. Plan 2b's catalog numbers moved to v31/v54.** **Plan 2b landed 2026-09-14 (`e6b87359e..fade39b90`, profile v54 / skill v31 / prompt v10): the fifteen-chapter operating manual as catalog skills (four generated + drift-tested, eleven hand-written pending founder review), disclosed by the capability map and opened by `read_file`; the L1 identity budget rose to 40,000 bytes; proven live with three questions each answered from the right chapter. The four §9 founder decisions are ruled provisionally as "document current behaviour"; see the note's plan-2b section.** **Plan 3 landed 2026-09-14 (`da7e4e7c3..7a4bd36cb`, profile v55 / skill v32 / recipe 27 / manual v2): `project/` is now a versioned root — the Head of ABM writes the ICP, the personas and the plan with the ordinary `write_file` (kind by folder, refusals as `conflict: <code>: <message>`), the turn's written rows become the Plan/ICP/Personas cards, and `author_icp_document@1`, `write_project_document@1` and `request_persona_synthesis@1` are ungranted (registered for replay only); the live proof is owed — see the note's plan-3 section.** The founder's own 27-item walk of the 2026-09-12 plans is still owed. **Plan 3 proven 2026-09-14 (`da7e4e7c3..94ef21dd1`, profile v55 / skill v32 / recipe 27 / manual v2): `write_file`/`edit_file` under `project/` land document versions through the versioned root; personas v2, plan v1→v2 (human PUT)→v3 (agent, keeping the edit) proven live; two live-proof fixes (bridge-bound artifact reader; stream-chunk timeout 300 s).** **Plan 4 landed 2026-09-14 (`2a9d23d15..f8524ed64`, profile v56 / skill v33 / recipe 28 / manual v3, context policies at v3): layer budgets became tracking-only (no turn fails or loses context at assembly), the two reads page at `read_discovery_run@2` / `read_account_research@2`, `read_claims@1` and `read_artifact@1` joined them, a governed result over 12 KiB spills to `reads/<operation_id>.json` and the receipt points at it (at both receipt-build sites), and any markdown under `project/` is now a free-flowing versioned document whose plan/persona/ICP role is a pin the human agrees to (migration `639d081ad799`) — the live proof is owed; see the note's plan-4 section.** **Plan 4 proven 2026-09-14 (`584cae976..848230dd6`, profile v57 / skill v33 / recipe 28 / manual v4): paged reads at @2, `read_claims@1`, `read_artifact@1`, spills to `reads/`, free-flowing documents with `role:` pins, context budgets tracked not enforced, turn caps 1800 s / 100 rounds — all proven live except `read_artifact` (no gallery on the project).**
- `2026-09-13-live-walk-findings-and-workspace-reorg.md` — plan 4 in anger: the "what was researched about Arthur Direct Care?" turn died on five causes (`read_discovery_run` output-contract bug on the `pass` alias; the claims read overflows the 16 KiB governed receipt; `overview_not_written` is honest because overviews render on first page view; a guessed `field_prefix`; the per-turn failure budget of 3 spent by a parallel fan-out). The workspace as it really is (one directory per turn, ids derived by uuid5, isolation per workspace) and the founder's reorganisation rulings W1–W11 → `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` (four-level workspace, project library as a materialized view, one save tool + document skills, paged/spilled reads, personas by the Head of ABM). **Hotfix landed 2026-09-13 night (lane-1 plan 0, `0b1975628..423e5bb40`, profile v50 / skill v27) and proven live on the lane stack — the paged Prevea Health read and the discovery read both complete; see the note's plan-0 section.** **Plan 1 landed the same night (`24650d9f2..5e2557a73`, profile v51 / skill v28, migration `5e78522ddf48`): one persistent workspace directory per chat thread with `scratch/` and `reads/`, mounts on the backend, per-turn rewrite of the platform trees, outputs snapshotted then emptied, retention by thread — proven live with a two-turn notebook walk; see the note's plan-1 section.** **Plan 2 landed 2026-09-14 (`3b236c669..670c76e3d`, profile v53 / skill v30 / prompt v9): the brand library once per knowledge version mounted read-only as `brand/`, the project library (status, decisions, one version per document, artifact index) compiled from rows and mounted as `project/`, the turn pins the library manifest and replays from the pinned set, writers and DSAR refresh it — proven live with reads of `project/status.md` and `brand/index.json`; see the note's plan-2 section. Plan 2b's catalog numbers moved to v31/v54.** **Plan 2b landed 2026-09-14 (`e6b87359e..fade39b90`, profile v54 / skill v31 / prompt v10): the fifteen-chapter operating manual as catalog skills (four generated + drift-tested, eleven hand-written pending founder review), disclosed by the capability map and opened by `read_file`; the L1 identity budget rose to 40,000 bytes; proven live with three questions each answered from the right chapter. The four §9 founder decisions are ruled provisionally as "document current behaviour"; see the note's plan-2b section.** **Plan 3 landed 2026-09-14 (`da7e4e7c3..7a4bd36cb`, profile v55 / skill v32 / recipe 27 / manual v2): `project/` is now a versioned root — the Head of ABM writes the ICP, the personas and the plan with the ordinary `write_file` (kind by folder, refusals as `conflict: <code>: <message>`), the turn's written rows become the Plan/ICP/Personas cards, and `author_icp_document@1`, `write_project_document@1` and `request_persona_synthesis@1` are ungranted (registered for replay only); the live proof is owed — see the note's plan-3 section.** The founder's own 27-item walk of the 2026-09-12 plans is still owed. **Plan 3 proven 2026-09-14 (`da7e4e7c3..94ef21dd1`, profile v55 / skill v32 / recipe 27 / manual v2): `write_file`/`edit_file` under `project/` land document versions through the versioned root; personas v2, plan v1→v2 (human PUT)→v3 (agent, keeping the edit) proven live; two live-proof fixes (bridge-bound artifact reader; stream-chunk timeout 300 s).** **Plan 4 landed 2026-09-14 (`2a9d23d15..f8524ed64`, profile v56 / skill v33 / recipe 28 / manual v3, context policies at v3): layer budgets became tracking-only (no turn fails or loses context at assembly), the two reads page at `read_discovery_run@2` / `read_account_research@2`, `read_claims@1` and `read_artifact@1` joined them, a governed result over 12 KiB spills to `reads/<operation_id>.json` and the receipt points at it (at both receipt-build sites), and any markdown under `project/` is now a free-flowing versioned document whose plan/persona/ICP role is a pin the human agrees to (migration `639d081ad799`) — the live proof is owed; see the note's plan-4 section.**
- `2026-09-13-live-walk-findings-and-workspace-reorg.md` — plan 4 in anger: the "what was researched about Arthur Direct Care?" turn died on five causes (`read_discovery_run` output-contract bug on the `pass` alias; the claims read overflows the 16 KiB governed receipt; `overview_not_written` is honest because overviews render on first page view; a guessed `field_prefix`; the per-turn failure budget of 3 spent by a parallel fan-out). The workspace as it really is (one directory per turn, ids derived by uuid5, isolation per workspace) and the founder's reorganisation rulings W1–W11 → `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` (four-level workspace, project library as a materialized view, one save tool + document skills, paged/spilled reads, personas by the Head of ABM). **Hotfix landed 2026-09-13 night (lane-1 plan 0, `0b1975628..423e5bb40`, profile v50 / skill v27) and proven live on the lane stack — the paged Prevea Health read and the discovery read both complete; see the note's plan-0 section.** **Plan 1 landed the same night (`24650d9f2..5e2557a73`, profile v51 / skill v28, migration `5e78522ddf48`): one persistent workspace directory per chat thread with `scratch/` and `reads/`, mounts on the backend, per-turn rewrite of the platform trees, outputs snapshotted then emptied, retention by thread — proven live with a two-turn notebook walk; see the note's plan-1 section.** **Plan 2 landed 2026-09-14 (`3b236c669..670c76e3d`, profile v53 / skill v30 / prompt v9): the brand library once per knowledge version mounted read-only as `brand/`, the project library (status, decisions, one version per document, artifact index) compiled from rows and mounted as `project/`, the turn pins the library manifest and replays from the pinned set, writers and DSAR refresh it — proven live with reads of `project/status.md` and `brand/index.json`; see the note's plan-2 section. Plan 2b's catalog numbers moved to v31/v54.** **Plan 2b landed 2026-09-14 (`e6b87359e..fade39b90`, profile v54 / skill v31 / prompt v10): the fifteen-chapter operating manual as catalog skills (four generated + drift-tested, eleven hand-written pending founder review), disclosed by the capability map and opened by `read_file`; the L1 identity budget rose to 40,000 bytes; proven live with three questions each answered from the right chapter. The four §9 founder decisions are ruled provisionally as "document current behaviour"; see the note's plan-2b section.** **Plan 3 landed 2026-09-14 (`da7e4e7c3..7a4bd36cb`, profile v55 / skill v32 / recipe 27 / manual v2): `project/` is now a versioned root — the Head of ABM writes the ICP, the personas and the plan with the ordinary `write_file` (kind by folder, refusals as `conflict: <code>: <message>`), the turn's written rows become the Plan/ICP/Personas cards, and `author_icp_document@1`, `write_project_document@1` and `request_persona_synthesis@1` are ungranted (registered for replay only); the live proof is owed — see the note's plan-3 section.** The founder's own 27-item walk of the 2026-09-12 plans is still owed. **Plan 3 proven 2026-09-14 (`da7e4e7c3..94ef21dd1`, profile v55 / skill v32 / recipe 27 / manual v2): `write_file`/`edit_file` under `project/` land document versions through the versioned root; personas v2, plan v1→v2 (human PUT)→v3 (agent, keeping the edit) proven live; two live-proof fixes (bridge-bound artifact reader; stream-chunk timeout 300 s).**
- `2026-09-13-live-walk-findings-and-workspace-reorg.md` — plan 4 in anger: the "what was researched about Arthur Direct Care?" turn died on five causes (`read_discovery_run` output-contract bug on the `pass` alias; the claims read overflows the 16 KiB governed receipt; `overview_not_written` is honest because overviews render on first page view; a guessed `field_prefix`; the per-turn failure budget of 3 spent by a parallel fan-out). The workspace as it really is (one directory per turn, ids derived by uuid5, isolation per workspace) and the founder's reorganisation rulings W1–W11 → `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` (four-level workspace, project library as a materialized view, one save tool + document skills, paged/spilled reads, personas by the Head of ABM). **Hotfix landed 2026-09-13 night (lane-1 plan 0, `0b1975628..423e5bb40`, profile v50 / skill v27) and proven live on the lane stack — the paged Prevea Health read and the discovery read both complete; see the note's plan-0 section.** **Plan 1 landed the same night (`24650d9f2..5e2557a73`, profile v51 / skill v28, migration `5e78522ddf48`): one persistent workspace directory per chat thread with `scratch/` and `reads/`, mounts on the backend, per-turn rewrite of the platform trees, outputs snapshotted then emptied, retention by thread — proven live with a two-turn notebook walk; see the note's plan-1 section.** **Plan 2 landed 2026-09-14 (`3b236c669..670c76e3d`, profile v53 / skill v30 / prompt v9): the brand library once per knowledge version mounted read-only as `brand/`, the project library (status, decisions, one version per document, artifact index) compiled from rows and mounted as `project/`, the turn pins the library manifest and replays from the pinned set, writers and DSAR refresh it — proven live with reads of `project/status.md` and `brand/index.json`; see the note's plan-2 section. Plan 2b's catalog numbers moved to v31/v54.** **Plan 2b landed 2026-09-14 (`e6b87359e..fade39b90`, profile v54 / skill v31 / prompt v10): the fifteen-chapter operating manual as catalog skills (four generated + drift-tested, eleven hand-written pending founder review), disclosed by the capability map and opened by `read_file`; the L1 identity budget rose to 40,000 bytes; proven live with three questions each answered from the right chapter. The four §9 founder decisions are ruled provisionally as "document current behaviour"; see the note's plan-2b section.** **Plan 3 landed 2026-09-14 (`da7e4e7c3..7a4bd36cb`, profile v55 / skill v32 / recipe 27 / manual v2): `project/` is now a versioned root — the Head of ABM writes the ICP, the personas and the plan with the ordinary `write_file` (kind by folder, refusals as `conflict: <code>: <message>`), the turn's written rows become the Plan/ICP/Personas cards, and `author_icp_document@1`, `write_project_document@1` and `request_persona_synthesis@1` are ungranted (registered for replay only); the live proof is owed — see the note's plan-3 section.** The founder's own 27-item walk of the 2026-09-12 plans is still owed.
- `2026-09-13-live-walk-findings-and-workspace-reorg.md` — plan 4 in anger: the "what was researched about Arthur Direct Care?" turn died on five causes (`read_discovery_run` output-contract bug on the `pass` alias; the claims read overflows the 16 KiB governed receipt; `overview_not_written` is honest because overviews render on first page view; a guessed `field_prefix`; the per-turn failure budget of 3 spent by a parallel fan-out). The workspace as it really is (one directory per turn, ids derived by uuid5, isolation per workspace) and the founder's reorganisation rulings W1–W11 → `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` (four-level workspace, project library as a materialized view, one save tool + document skills, paged/spilled reads, personas by the Head of ABM). **Hotfix landed 2026-09-13 night (lane-1 plan 0, `0b1975628..423e5bb40`, profile v50 / skill v27) and proven live on the lane stack — the paged Prevea Health read and the discovery read both complete; see the note's plan-0 section.** **Plan 1 landed the same night (`24650d9f2..5e2557a73`, profile v51 / skill v28, migration `5e78522ddf48`): one persistent workspace directory per chat thread with `scratch/` and `reads/`, mounts on the backend, per-turn rewrite of the platform trees, outputs snapshotted then emptied, retention by thread — proven live with a two-turn notebook walk; see the note's plan-1 section.** **Plan 2 landed 2026-09-14 (`3b236c669..670c76e3d`, profile v53 / skill v30 / prompt v9): the brand library once per knowledge version mounted read-only as `brand/`, the project library (status, decisions, one version per document, artifact index) compiled from rows and mounted as `project/`, the turn pins the library manifest and replays from the pinned set, writers and DSAR refresh it — proven live with reads of `project/status.md` and `brand/index.json`; see the note's plan-2 section. Plan 2b's catalog numbers moved to v31/v54.** **Plan 2b landed 2026-09-14 (`e6b87359e..fade39b90`, profile v54 / skill v31 / prompt v10): the fifteen-chapter operating manual as catalog skills (four generated + drift-tested, eleven hand-written pending founder review), disclosed by the capability map and opened by `read_file`; the L1 identity budget rose to 40,000 bytes; proven live with three questions each answered from the right chapter. The four §9 founder decisions are ruled provisionally as "document current behaviour"; see the note's plan-2b section.** The founder's own 27-item walk of the 2026-09-12 plans is still owed.
- `2026-09-13-live-walk-findings-and-workspace-reorg.md` — plan 4 in anger: the "what was researched about Arthur Direct Care?" turn died on five causes (`read_discovery_run` output-contract bug on the `pass` alias; the claims read overflows the 16 KiB governed receipt; `overview_not_written` is honest because overviews render on first page view; a guessed `field_prefix`; the per-turn failure budget of 3 spent by a parallel fan-out). The workspace as it really is (one directory per turn, ids derived by uuid5, isolation per workspace) and the founder's reorganisation rulings W1–W11 → `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` (four-level workspace, project library as a materialized view, one save tool + document skills, paged/spilled reads, personas by the Head of ABM). **Hotfix landed 2026-09-13 night (lane-1 plan 0, `0b1975628..423e5bb40`, profile v50 / skill v27) and proven live on the lane stack — the paged Prevea Health read and the discovery read both complete; see the note's plan-0 section.** **Plan 1 landed the same night (`24650d9f2..5e2557a73`, profile v51 / skill v28, migration `5e78522ddf48`): one persistent workspace directory per chat thread with `scratch/` and `reads/`, mounts on the backend, per-turn rewrite of the platform trees, outputs snapshotted then emptied, retention by thread — proven live with a two-turn notebook walk; see the note's plan-1 section.** **Plan 2 landed 2026-09-14 (`3b236c669..670c76e3d`, profile v53 / skill v30 / prompt v9): the brand library once per knowledge version mounted read-only as `brand/`, the project library (status, decisions, one version per document, artifact index) compiled from rows and mounted as `project/`, the turn pins the library manifest and replays from the pinned set, writers and DSAR refresh it — proven live with reads of `project/status.md` and `brand/index.json`; see the note's plan-2 section. Plan 2b's catalog numbers move to v31/v54.** The founder's own 27-item walk of the 2026-09-12 plans is still owed.
- `2026-09-13-live-walk-findings-and-workspace-reorg.md` — plan 4 in anger: the "what was researched about Arthur Direct Care?" turn died on five causes (`read_discovery_run` output-contract bug on the `pass` alias; the claims read overflows the 16 KiB governed receipt; `overview_not_written` is honest because overviews render on first page view; a guessed `field_prefix`; the per-turn failure budget of 3 spent by a parallel fan-out). The workspace as it really is (one directory per turn, ids derived by uuid5, isolation per workspace) and the founder's reorganisation rulings W1–W11 → `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` (four-level workspace, project library as a materialized view, one save tool + document skills, paged/spilled reads, personas by the Head of ABM). **Hotfix landed 2026-09-13 night (lane-1 plan 0, `0b1975628..423e5bb40`, profile v50 / skill v27) and proven live on the lane stack — the paged Prevea Health read and the discovery read both complete; see the note's plan-0 section.** **Plan 1 landed the same night (`24650d9f2..5e2557a73`, profile v51 / skill v28, migration `5e78522ddf48`): one persistent workspace directory per chat thread with `scratch/` and `reads/`, mounts on the backend, per-turn rewrite of the platform trees, outputs snapshotted then emptied, retention by thread — proven live with a two-turn notebook walk; see the note's plan-1 section.** The founder's own 27-item walk of the 2026-09-12 plans is still owed.
- `2026-09-13-live-walk-findings-and-workspace-reorg.md` — plan 4 in anger: the "what was researched about Arthur Direct Care?" turn died on five causes (`read_discovery_run` output-contract bug on the `pass` alias; the claims read overflows the 16 KiB governed receipt; `overview_not_written` is honest because overviews render on first page view; a guessed `field_prefix`; the per-turn failure budget of 3 spent by a parallel fan-out). The workspace as it really is (one directory per turn, ids derived by uuid5, isolation per workspace) and the founder's reorganisation rulings W1–W11 → `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` (four-level workspace, project library as a materialized view, one save tool + document skills, paged/spilled reads, personas by the Head of ABM). **Hotfix landed 2026-09-13 night (lane-1 plan 0, `0b1975628..423e5bb40`, profile v50 / skill v27) and proven live on the lane stack — the paged Prevea Health read and the discovery read both complete; see the note's last section.** The founder's own 27-item walk of the 2026-09-12 plans is still owed.
- `2026-09-13-live-walk-findings-and-workspace-reorg.md` — plan 4 in anger: the "what was researched about Arthur Direct Care?" turn died on five causes (`read_discovery_run` output-contract bug on the `pass` alias; the claims read overflows the 16 KiB governed receipt; `overview_not_written` is honest because overviews render on first page view; a guessed `field_prefix`; the per-turn failure budget of 3 spent by a parallel fan-out). The workspace as it really is (one directory per turn, ids derived by uuid5, isolation per workspace) and the founder's reorganisation rulings W1–W11 → `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` (four-level workspace, project library as a materialized view, one save tool + document skills, paged/spilled reads, personas by the Head of ABM). Hotfix owed first; live walk still owed.
- `2026-09-14-lane2-plan-tab-preview.md` — Lane 2 step 4 visual preview; Plan-tab production wiring awaits review.
- `2026-09-14-lane2-shared-markdown-knowledge.md` — Lane 2 Task 5 shared editor, Knowledge lifecycle and live acceptance.
- `2026-09-16-provider-incidents.md` — provider incidents end to end (classifier, `provider_incident` table + Sentry open/close, the drain and chat-turn writers, three inline surfaces); rulings PI-1..PI-5, the live Exa refusal→recovery proof, and what the founder's browser walk still owes.
- `2026-09-17-composer-file-tagging.md` — composer `@` tagging of Gallery files, microsites and accounts: the clipped-picker fix (`89f34dd4e`), the approved spec and the 8-task plan; execution not started (founder ruling); rulings and the one spec deviation recorded.
- `2026-09-17-custom-domain-publishing-research.md` — custom-domain publishing for web pages: what the tree actually serves today (interim `/w/{ws}/p/{slug}`, hardcoded `share.cluehq.ai` chrome, tenant-subdomain v1 unbuilt, absolute asset URLs baked at publish), how Notion/Mutiny/Ploy do it, Railway 20-domains-per-service cap, Cloudflare-for-SaaS recommendation, which dummy Pages fields to keep/drop; section-20 rules + Option C RATIFIED; design approved; spec at `docs/superpowers/specs/2026-09-17-custom-domain-publishing-design.md`. No code.
- `2026-09-18-design-session-continuity.md` — the design agent's durable session (one workspace and one thread per design session, continue/resume, session sync through the blob store, erasure), then the 2026-09-19 exit judge v2 (free reasoning + three engine actions, artifact and tags shown), and the **seller + target-account context** shipped the same day on `design-agent-account-context-transfer`: the design role is granted `read_project_accounts@1` / `read_account_research@2` / `read_claims@1`, they reach the runtime as tools on LEG turns only, a governed refusal arrives as `{"error": "refused", "reasons": [...]}`, the seller's pinned knowledge documents are written read-only into `workspace/seller/` with an `index.md`, and the account-adaptation / scene-brief-copy / tools skills teach all of it. **Skill text pending founder review; the three live acceptance proofs (spec §6) are owed.**
- `2026-09-21-display-prewrite-planning.md` — how display prose is generated today (lazy on read, Luna per section, `display_block`), the 09-12 prewrite design found unimplemented, the 09-21 placeholder ruling (`Synthesis in progress…`, `pending`, 5 s poll), and the 8-task plan `docs/superpowers/plans/2026-09-21-display-prewrite-and-shared-blocks.md`. Execution not started.
- `2026-09-21-display-prewrite-execution.md` — execution record for `display/prewrite-and-shared-blocks`: display prose is now written by the fleet (`arv2_display_page` kind + handler, the account overview offered at settle, the contact pages of an account on its first open), a read became a scheduler (`pending` + `Synthesis in progress, please wait a few seconds.` + a 5 s `router.refresh()` poll), and the insights page's `context-only` / `contact-insights` are the owners' stored blocks. Eight tasks, two migrations (`fd8795c4fd5a`, `2b702a116c15`); rulings, gates and the five owed live proofs recorded there.
