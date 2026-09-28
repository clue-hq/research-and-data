# 2026-09-27 — WVI (website de-anonymization) worktree kickoff: fastest build path

Branch `feature/website-deanonymization`, worktree `/Users/shashank/Documents/clue-accounts/website-deanonymization-feature`,
based on `install-agent-browser-global-v1` @ `cc695283e` (the only line carrying the WVI specs; 73 ahead / 1 behind
`origin/main` — the one missing commit is the PR #44 merge, fold it in before the first PR).
Specs: `docs/specs/WVI-website-visitor-identification.md` (WVI-1, seams §4, checklist §6, phases §7, rulings W1–W9)
and `docs/specs/WVI-2-research-register-and-90pct-blueprint.md` (components C1–C12, phases §4.5).

## Facts re-verified at kickoff (this worktree)
- `account_activity_event` (ARV2 D1/D3) exists in specs only — no table, no migration, no read path. Ruling W9
  ("V0 after D3") would block V0 on ARV2; **decision for speed: WVI owns its own tables and serves `visit`
  activity from `visitor_resolution`**, ARV2 D3 adopts it later.
- No AI Ark client (`arv2/ai_ark_client.py` absent) — only matters for rung 2 (V2).
- No tracking/consent/reverse-IP/ipregistry/GPC code anywhere (unchanged since 2026-09-24).
- Page route `GET /w/{workspace_id}/p/{slug}` lives in the design API (`subsystems/clue-design/apps/api`); CSP is
  `connect-src 'none'` → collect server-side (ruling W4).
- `FleetTaskKind` at `platform/fleet/clue_fleet/enums.py:17`; `ALTER TYPE fleet_task_kind ADD VALUE` precedents
  `be855c8f6993`, `d9b39fb407ed`, `022b1154b3aa`. Alembic: `alembic/versions` (206 files), hash ids, one head.
- Source seeds helper `sources/seeds.py::_entry` (line 30). Inbound webhook shape: `ExaWebhookIngestor`
  (`platform/api/clue_api/exa_websets_lifecycle.py:285`).
- Frontend Activity kinds are a closed 3-value zod enum (`apps/frontend/src/features/accounts/model/account-activity.ts`).

## Fastest path = V0 only (no vendor, no script, no ARV2 dependency), five slices
A. **Migration + registry** (one hash-id migration): `visitor_link`, `web_visit_event`, `visitor_resolution`;
   `fleet_task_kind += 'visitor_resolve'`; field rows `account.web_engagement` / `contact.web_engagement`
   (`signal_class="intent"`) + `account.visiting_company`; source manifests `visitor_link` (tier 1 STRONG) and
   `reverse_ip` (tier 2 WEAK). Flags in `.env.example` in the same commit (`CLUE_WVI_ENABLED=false`,
   `CLUE_WVI_PERSON_LEVEL=off`, `CLUE_WVI_REVERSE_IP_PROVIDER=ipregistry`, `CLUE_WVI_MONTHLY_REVEAL_CAP=500`,
   `CLUE_WVI_RAW_IP_RETENTION_DAYS=30`, `CLUE_IPREGISTRY_API_KEY=`).
B. **Collector on Clue pages** (design API page handler): read+strip `?cl=`, set `clue_vid` (13 mo), UA bot filter,
   write `web_visit_event` (raw IP, referrer, utm, geo_country, consent_state=not_required), enqueue
   `visitor_resolve` with `dedup_key=visitor-resolve:{visitor_id}:{day}`.
C. **Token minting**: `visitor_link` writer + `POST /frontend/v1/visitor-links` + "Copy tracked link" on the
   account/contact screens (frontend repo seam: zod model + repository + fixture/HTTP adapters, no component logic).
D. **Resolution handler** (`visitor_resolve`): rung 0 token → STRONG contact/account bind; rung 1 reverse IP via an
   `ipregistry` `Resolver` (exclude isp/hosting/vpn/relay/bot; `identity.resolve(Observation(domain))` in-workspace;
   unknown domain → `visiting_company` suggestion, never an account). One transaction: `visitor_resolution` row +
   claims via `insert_claim` + cost-ledger row. Never any person-level call in V0.
E. **Read side**: Activity tab kind `visit` served from `visitor_resolution` (backend projection + zod enum);
   `contact.web_engagement` added to `CONTACT_SIGNAL_FIELD_KEYS`; `account.web_engagement` renders generically.

V0 exit gate (WVI-1 §7): tracked link in an email → contact Activity shows the visit with channel/pages within
60 s; untracked corporate-IP visit shows as the account; a Private Relay visit is "unknown".
Then V1 (`clue.js`, `/v1/collect`, consent/GPC/jurisdiction, DSAR selector, retention job), V2 (rung 2 person-level
behind `CLUE_WVI_PERSON_LEVEL=us_only`, Leadpipe/RB2B + AI Ark, cap, review), V3 (agent read tool, CRM outbox).

## Rulings needed before V0 code (recommendations from WVI-1 §8)
W3 token in URL (`?cl=`, opaque) — yes · W4 server-side only on Clue pages — yes · W9 amended: V0 does NOT wait for
ARV2 D3 (see facts). W1/W2/W6/W7 (provider, EU never, default off, credit unit) are V2 decisions.

## State
No code yet in this worktree; this note is the first commit. `pricing-strategy/` and `.context/` stay uncommitted.

## Addendum (same day) — deep research + implementation plan
Delivered **`docs/specs/WVI-3-implementation-plan.md`** (supersedes WVI-1 §4/§6/§7 and WVI-2 §4.5 where they differ).
Five research agents (3 repo seams, 2 web). Corrections to the earlier specs found in code:
- Web batch derive passes flat `account_values`, no `BindingSet` → `InstanceLink`/`UrlQr` unreachable for web pages;
  V0 mints tokens via `POST /frontend/v1/visitor-links`, automatic minting goes through `account_values` (V3).
- `/w/` page routes are temporary (Part IV deletes them) → collector hook lives in the app middleware
  (`lumen_api/main.py:779-836`); `lumen_api` may lazily import `clue_fleet` (precedent `design_store.py:1813-1847`),
  `clue_design` may not; collector writes `web_visit_event` via raw SQL + enqueues `VISITOR_RESOLVE`.
- Published pages are `Cache-Control: public, max-age=60` with no 304 path and no Set-Cookie anywhere → switch to
  `private, no-cache` while collecting; `?cl=` reaches `uvicorn.access` logs → strip via 302 redirect.
- No proxy-header config; uvicorn trusts XFF only from 127.0.0.1 → `FORWARDED_ALLOW_IPS` needed on Railway.
- No published-page origin setting exists (origin frozen from the publishing request) → `CLUE_WVI_PUBLIC_PAGE_ORIGIN`.
- `research_subject_activity` needs project-run/account-run FKs → visits served from `visitor_resolution` via a
  second activity query; accounts contract forbids served display strings → structured `visit` variant.
- Contact "Recent signals" chip is count-only over facet keys with exact-set tests → separate served field.
- `signal_class` does nothing for scoring (needs `pass_kind=SCORING` + rubric entry) → V3.
- No workspace-level cost ledger → `visitor_resolution.cost_cents`; no AI Ark client exists yet.
- `claim.run_id` is NOT NULL uuid without FK → uuid5 per resolution; fields default PUBLIC → declare TENANT_PRIVATE.
- Accounts frontend is live-only (no fixture mode); no settings UI exists at all; no vitest (node:test only).
Web facts that shaped the design: pixel model = public per-domain id + host allowlist + path denylist (RB2B/Vector/
Leadpipe); LinkedIn exposes nothing per member (Insight Tag aggregated ≥300; `li_fat_id` resolves only inside
LinkedIn CAPI); LinkedInBot prefetches shared links (UA `LinkedInBot/1.0`, rDNS `*.fwd.linkedin.com`); ipregistry has
`company.type` + `security.is_vpn/is_relay/is_cloud_provider`, 20k free credits, EU base URL; Leadpipe webhook carries
`linkedin_url`; SB 690 passed 28 Aug, unsigned as of 27 Sep (deadline 30 Sep); EDPB 2/2023 ¶55 on IP + Art 5(3).
New rulings proposed W10–W13 (cache header, settings surface, rung-1 provider, rung-2 POC). No code yet.
