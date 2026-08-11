# FI-4 — Onboarding flow: frontend ⇄ backend contract-gap review

**Status: study complete — awaiting founder discussion and sign-off. Decisions in §8 are NOT ratified except where §9 records a founder ruling.**
Date: 2026-08-12. Branch: `platform/onboarding-integration` @ `e143e68a` (the selective import of the seven onboarding screens from `clue-frontend` `origin/onboarding-flow` @ `ab25e436`).
Method: three parallel read-only code studies (frontend onboarding + session/auth machinery; backend Stage-0 recon surface incl. the full event vocabulary; backend auth/workspace/brand provisioning), consolidated here. Frontend truth = the Zod schemas and components under `apps/frontend/src/features/onboarding/`; backend truth = code on this branch. Companion architecture: REQ-08 (`clue-hq-harness-architecture-and-requirements.md:441-537`), Doc B, `PC-C4-stage0-recipe0.md`, `FI-lane-B-authenticated-principal-contract.md`, `apps/frontend/docs/api-contracts/{onboarding,session}.md`.

Scope boundary (per REQ-08 / PC-C4 §1): these screens cover **workspace onboarding only** (auth → profile → name+URL → eager recon with visible progress). Project kickoff (interview, ICP confirmation, readiness, `record_interview_answer`) is the chat surface's job and is out of scope here.

---

## 0. Verdict in one paragraph

The screens and the architecture want the same product shape — minimum input (name + website), then real background research with honest progress — but almost none of the plumbing between them exists yet. Four independent gaps stack up: **(1)** the frontend's proposed auth endpoints contradict the ratified Clerk/Lane-B contract and its four auth screens are pure theatre (Google button routes straight to the profile step); **(2)** a fresh Clerk user dead-ends at `/access-denied` because nothing calls `provision_workspace_owner`, no brand-creation surface exists anywhere, and `brand_id` is `NOT NULL` on every Stage-0 table; **(3)** the profile screen's fields have nowhere to live (`platform_user` has only `display_name`); **(4)** `start_recon` structurally cannot run in production (scrape binder never composed; refuses `stage0_recon_not_configured` at every call site), the background lane has no driver, and the honest event vocabulary is 4 lane-transition events committed after-the-fact — nowhere near the 1:1 checklist REQ-08 and the founder demand. None of this blocks anything today because the screens are 100% fixture-backed; the contract can be renegotiated freely before any adapter flips.

---

## 1. Structural mismatches

- **S1 — Auth model.** Frontend contract proposes `POST /api/v1/auth/{google,sign-in,sign-up}` with passwords in the body (`onboarding.md:31-60`). The ratified Lane-B contract (§9-2026-08-08 ruling in FI-1; `session.md`) is: Clerk owns sign-in/sign-up/recovery entirely; the browser never calls a backend auth endpoint; the backend only verifies Clerk session JWTs. The already-integrated app has the Clerk routes (`/sign-in/[[...sign-in]]`, `/session/establish`, `/sign-out`) — but **no `/sign-up` route exists** (`src/app/(auth)/` contains none), and the stock `<SignIn>` widget carries none of the approved screen geometry. The four imported auth screens are currently pure navigation theatre: `authChoiceTarget` sends the Google button straight to `"profile"` (`onboarding-navigation.ts:17-23`); nothing touches Clerk.
- **S2 — Provisioning void.** `provision_workspace_owner` (`clue_auth/provisioning.py:175-207`) creates user + identity + workspace + owner membership — and has **zero HTTP callers** (only tests). There is no `POST /workspaces`, no brand endpoint, no product endpoint anywhere in `platform/api/`. A fresh Clerk sign-in gets 403 `IDENTITY_NOT_PROVISIONED` from `/auth/v1/session` (no `auth_identity` row); a provisioned-but-membership-less user gets `200 {memberships: []}`, which the frontend converts to `WORKSPACE_FORBIDDEN` → `redirect("/access-denied")` (`session-dal.ts:52-58`) — a terminal dead end whose only action is "sign in with a different account". Nothing routes anyone to `/onboarding`.
- **S3 — The brand chain.** `brand_id` is `NOT NULL` + FK on `onboarding_input`, `recon_run`, `project`, and `project_run` (`1b71451d48cd:161-266`, `b366c985ca12`). The hard dependency chain for a fresh signup is **identity → workspace → brand → onboarding_input/recon** (project/product stay nullable at this stage). `provision_workspace_owner` creates no brand; `GET /api/v1/home` on a zero-brand workspace returns `brands: [], default_brand_id: null` and the Home composer cannot create a project (`chat/router.py:660-686`). Workspace-setup must therefore create the first brand, or the user exits onboarding into an unusable workspace.
- **S4 — Profile fields have no home.** `platform_user` = `display_name` only (`9398ae4467e3:37-55`); no first/last name, role, company, email — and any new PII column must join `erase_platform_user`'s DSAR path (`store.py:789-836`). `workspace_membership.role_key` is the *authorization* role (`owner|admin|operator|viewer`) and must not be overloaded with the profile screen's job-title string ("Founder"/"Marketing"/…).
- **S5 — Recon cannot run and has no granular events.** `start_recon` requires a composed `stage0_scrape_binder`; it is `None` at all three `build_toolbelt` call sites (`projections_main.py:62`, `fleet_main.py:546`, `stage0_trial.py:581`) → every production call refuses `stage0_recon_not_configured` (`stage0_tools.py:696-718`). It is also withheld from every agent surface (`agent_registry_wiring.py:203-260`). The background lane has **no driver** — it runs only on a second `start_recon` invocation (`stage0_tools.py:810-872`); "two-speed" is sequential-on-re-call today. The full honest event vocabulary is **≤4 events** — `run.step.progress` with `payload.kind="stage0.recon.transition"`, `{lane: fast|background, status: running|completed|failed}` — emitted at 4 sites in `StartReconTool.invoke` and committed atomically per lane (one transaction, `stage0_tools.py:736`), so `running` and `completed` become visible simultaneously. No per-field/per-source/per-claim event exists anywhere in `reverse_profile` (`client_kb.py:131-282`; OTel spans only).
- **S6 — Transport.** The imported HTTP adapter fetches `{CLUE_API_BASE_URL}/api/v1/onboarding` **directly** — bypassing the BFF, no auth header, no error envelope, no idempotency (`onboarding.repository.ts:17-36`) — and that backend route does not exist. Recon's events are additionally unreachable over the B4 SSE surface: the stream-token mint 404s for anything without a `project_run` row (`projections_app.py:663-665`), and recon runs never create one — today's `stage0.recon.transition` rows are write-only. The polling projections **do** exist and are served: `GET /stage0/recon/{id}/progress` and `…/brief` (`projections_app.py:390-416`).

---

## 2. What the backend actually serves today (onboarding-relevant surfaces)

| Surface | Route | State |
|---|---|---|
| Session read | `GET /auth/v1/session` → `{user_id, memberships[]}` | live; membership-less = `200 []` |
| Principal read | `GET /auth/v1/principal` (+`X-Clue-Workspace-Id`) | live |
| Provisioning | — | **none** (`provision_workspace_owner` / `accept_workspace_invitation` uncalled) |
| Brand/product create | — | **none** (fixtures/trial scripts only) |
| Onboarding input | `POST /tools/submit_onboarding_input` (needs a pre-captured same-workspace artifact) | works today |
| Start recon | `POST /tools/start_recon` | **always refuses** `stage0_recon_not_configured` (S5) |
| Recon progress | `GET /stage0/recon/{id}/progress` → lane statuses, KB versions, `failure_code`, readiness refs | live (poll only; no timestamps) |
| Recon brief | `GET /stage0/recon/{id}/brief` → `facts` over the 9 `client.*` baseline fields, `fast_cost_cents`, `background_pending` | live; `facts` populate only after the fast lane completes |
| SSE | `POST /project_runs/{id}/stream_token` + `GET …/events` | live but **unmintable for recon ids** |
| Frontend's proposed routes | `GET /api/v1/onboarding`, `PUT …/profile`, `POST …/setup`, `GET …/setup/{runId}`, `POST /api/v1/auth/*` | **none exist** |

Recon internals (for calibration): both lanes run the same `reverse_profile` over the 9 `client.*` baseline fields (`fields.py:59-69`); fast = source tiers ≤2 @ 5¢, background = tiers ≤3 @ 100¢ (`Stage0Policy`, `clue_config/stage0.py:67-75` — hardcoded module default, no per-workspace override). Dedupe = 24h TTL on `sha256(workspace, brand, product, casefold(website))` (`governed.py:342-350`) — workspace-local, so no cross-tenant reuse (B3 ruling honored).

---

## 3. Screen-by-screen mapping

### 3.1 Auth screens (sign-in, sign-in-email, sign-up, sign-up-email)

Nothing to map field-by-field: the backend surface is Clerk, not endpoints. The work is **re-implementing the four approved screen designs as Clerk custom UI** (Clerk's `useSignIn`/`useSignUp` hooks or Elements — the stock widget cannot render the approved geometry), adding the missing `/sign-up` route, and wiring Google as a Clerk OAuth strategy. The fixture's copy block (`auth.signIn/.signUp` titles/labels) stays frontend-owned — there is no reason a backend endpoint should serve button labels (see D-7 on retiring the `GET /api/v1/onboarding` read). Error mapping: Clerk field errors → the approved card geometry (contract note `onboarding.md:123-124` survives, just aimed at Clerk errors instead of a bespoke API).

### 3.2 Profile screen

| Frontend field | Backend home today | Gap |
|---|---|---|
| `firstName`, `lastName` | none (`platform_user.display_name` only) | new column(s) — D-3 |
| `role` (Founder/Marketing/…) | none; must NOT be `role_key` (S4) | new column — D-3 |
| `companyName` | `workspace.name` + `brand.name` at provisioning | D-2 |
| `companyWebsite` | becomes the recon identity: artifact bytes + `onboarding_input(kind=website)` + `start_recon(website=…)` | D-4 |
| (email) | Clerk-owned; backend deliberately stores no address | render from Clerk session |

The proposed `PUT /api/v1/onboarding/profile` → "return the persisted profile plus a stable workspace identifier" is directionally right and becomes the **provisioning call** (D-2): it must create identity link + workspace + first brand + owner membership + profile row(s) in one idempotent transaction. Two backend facts force decisions: `provision_workspace_owner` is **not idempotent** (a replayed call creates a second workspace — `test_identity_substrate.py:170-185`), and every new PII column must join the DSAR erasure path.

Frontend defects to fix regardless: the draft is client-local and **lost on every route transition** (each step remounts the controller — `use-onboarding-controller.ts:25-33`); the profile form has zero validation (empty form advances); the header's "Log out" button has no handler.

### 3.3 Setup screens (setting-up, finalizing)

The contract's shape is right (`POST …/setup` → 202 + durable `runId`; resumable progress read; "the client timer is presentation only") and maps onto `recon_run` — but the composition behind it doesn't exist:

1. **Start** = capture the website submission as a B2 artifact (sha-256'd bytes; capture happens outside the tool), `submit_onboarding_input` (kind=`website`, actor=`human`), then `start_recon`. Needs: the scrape binder composed at the API root (`build_stage0_scrape_binder` — exists, only tests call it), a background-lane driver (S5), and a decision on where this composition lives (D-4).
2. **Progress** = today only lane-level polling (§2). The fixture's 4-item checklist has **no backing**: `company-products` loosely ≈ the 9 `client.*` fields; `brand-kit` is the design subsystem's share (not on this branch — §9 ruling: dummy or omit); `competitors` and `buyers` are **not things recon researches at all** (they are ICP-synthesis-era concerns). An honest checklist must be rebuilt from the real vocabulary — §4 / D-5, D-6.
3. **Exit**: `finalizing` is a dead end (`submitTarget("finalizing") === null`); fast-lane completion should release the user into the app (`/session/establish` → `/`) while the background lane continues — REQ-08's two-speed intent. Blocking until background completion is explicitly wrong.

---

## 4. The progress-event gap (the centerpiece)

Founder requirement (re-affirmed 2026-08-12, echoing REQ-08): *checklist ticks map 1:1 to emitted recon events — no fake, fixture-based progress.* What exists vs what's needed:

| | today | needed for 1:1 ticks |
|---|---|---|
| Event grain | 2/lane, post-hoc (atomic commit) | per-step, in-flight |
| Vocabulary | `stage0.recon.transition{lane,status}` | named steps a human can read |
| Transport | poll `/stage0/recon/{id}/progress` | poll is *acceptable* (states are durable); SSE is better UX |
| Per-field visibility | `brief.facts` after fast lane completes | incremental |

Two honest paths (D-5 picks one):

- **Path A — lane-level MVP.** Ship the checklist off the real polling surface with items that only claim what's true: "Researching your company (fast pass)" ← `fast_status`, "Deep background research" ← `background_status`, plus a fact-count reveal from `brief.facts` when fast completes. Brand-kit item rendered as static dummy (§9). No backend event work; smallest possible surface; the checklist has 2 live items.
- **Path B — granular events (the REQ-08 end-state).** Add per-field emission inside `reverse_profile`'s field loop (`client_kb.py:216-260`): one `run.step.progress` event per baseline-field resolution (started/resolved/skipped), same `run_event` substrate, new `payload.kind` (e.g. `stage0.recon.field`). 9 fields × 2 lanes gives real tick material; the frontend groups them into 2–4 designer-friendly checklist items (e.g. "Understanding your product & value" ← `client.{product,value_prop,differentiator}`; "Pricing & proof" ← `client.{pricing_posture,proof_point}`; "Customers & market" ← `client.{customer,icp_evidence,market_reputation,delivered_value}`). Requires: the emission change, per-event commit visibility (the current single-transaction shape defeats in-flight progress — either commit per field or read events uncommitted-tolerant), and a transport decision (extend the SSE token mint to recon ids, or poll a new event-cursor read).

Either path also needs the **background-lane driver** decision (D-4c): inline re-invoke after fast completes (simplest; blocks one request), a post-fast kicker at the API root, or a fleet job. And note `budget_exhausted` is currently discarded (`stage0_tools.py:799-802`) — a truncated lane is durably indistinguishable from a complete one, which an honest progress surface should probably expose (B-2 in §5).

---

## 5. Latent defects found during the study (fix regardless of decisions)

Frontend: **F1** — the imported HTTP adapter activates on the *shared* `CLUE_API_BASE_URL` (set in `.env.example` for auth) and fetches a nonexistent route directly, so any auth-configured env crashes the onboarding screens the moment they render (`onboarding.repository.ts:38-45`); **F2** — profile draft lost across step remounts (§3.2); **F3** — `finalizing` has no exit route; **F4** — `access-denied/page.tsx` has its `Link` import *after* the default export (works via hoisting; lint anomaly); **F5** — "Log out" button is a no-op `<button>`.

Backend: **B-1** — `recon_run` lane timestamps (`*_started_at`/`*_completed_at`) are written but never selected by any reader (`governed.py:180-186`); **B-2** — `ReverseProfileResult.budget_exhausted` discarded (§4); **B-3** — `failure_code` stores `type(exc).__name__` — a raw Python class name, not a reason-code taxonomy — and the progress projection serves it verbatim; **B-4** — `run.step.progress` carries two different payload shapes (recon transitions vs phase-planner `{from_phase,to_phase,…}`) distinguishable only by `payload.kind` — consumers must discriminate, and the discriminator string is an unnamed literal; **B-5** — `provision_workspace_owner` non-idempotent w.r.t. workspace creation (§3.2); **B-6** — recon events unreachable over SSE (write-only rows, S6).

---

## 6. Governance flags (decisions, never silent mappings)

- **G1 — Profile PII.** First/last name, job role are new personal-data categories on `platform_user`. Whatever schema lands (D-3) must extend `erase_platform_user` and the `IdentityBundle` DSAR surface in the same change — the substrate's erasure contract currently treats `display_name` as the entire profile.
- **G2 — The signup abuse envelope.** REQ-08 names the vector: 50 pasted URLs must cost cents. The 24h dedupe + 5¢/105¢ envelopes exist per-recon, but nothing rate-limits *workspace creation* itself once a provisioning endpoint exists (each signup = new workspace = fresh dedupe scope). The provisioning endpoint needs its own throttle stance, even a crude one.
- **G3 — Recon claims provenance.** The website submission must be captured as a real artifact (sha-256'd bytes) *before* `submit_onboarding_input` — the tool verifies existence and workspace-locality but capture is the caller's job; the composition endpoint owns writing that artifact through the B2 storage seam, not a synthetic placeholder.

---

## 7. What stays out of scope (explicit)

Interview/`record_interview_answer`, readiness evaluation/override, ICP synthesis/confirmation, `confirm_project_product`, project creation, `start_confirmed_project_run` — all project-kickoff surfaces (PC-C4 Recipe #0 beyond `start_recon`). The onboarding screens end at "fast recon done, user released into the app, background recon continuing." Also out: brand-kit extraction (design subsystem; §9 ruling) and any product/`product_id` handling — onboarding runs product-less by design (`onboarding_input.product_id` nullable; products enter at project kickoff, REQ-22).

---

## 8. Decision register (for founder sign-off)

- **D-1 — Auth = Clerk headless behind the unchanged approved screens** *(visual-fidelity half RATIFIED — §9 2026-08-12)*. Reject `POST /api/v1/auth/*` (contradicts the ratified Lane-B contract). The four approved auth screens keep their exact visual appearance — same components, same CSS module, same geometry; Clerk is wired **headless-only** underneath via the custom-flow hooks (`useSignIn`/`useSignUp`), replacing the controller's fake navigation with real credential flows (Google = Clerk OAuth strategy redirect; email+password = `signIn.create`/`signUp.create`). No Clerk prebuilt component, no Clerk-rendered UI, anywhere in onboarding; Clerk owns authentication and the session cookie, nothing more. The stock `<SignIn>` widget at `/sign-in` is superseded for this flow (remaining open sub-decision: whether `/sign-in` redirects into `/onboarding/sign-in` or survives as a dev-only fallback). Two fidelity risks to resolve at implementation, not discover in production: (a) Clerk bot protection injects a CAPTCHA element on sign-up — either disable it instance-wide or mount the invisible/smart variant inside the approved card without layout change; (b) if the Clerk instance requires email-verification codes, that is a screen the approved set does not contain — turn verification off, or the founder approves a designed step for it. Amend `onboarding.md` accordingly.
- **D-2 — The provisioning endpoint.** One idempotent backend transaction (new route, BFF-fronted; proposal: `POST /auth/v1/provision` or fold into the profile submit): resolve-or-create `auth_identity`+`platform_user` for the Clerk subject, create workspace (name = companyName), **create the first brand** (name = companyName), owner membership, persist profile fields. Idempotency key derived from the Clerk subject (fixes B-5 for this path: replay returns the existing workspace, never a second one). Decide: is identity provisioning lazy-on-first-session (kills the `IDENTITY_NOT_PROVISIONED` dead end for everyone) or part of this explicit call?
- **D-3 — Profile schema.** Where `firstName`/`lastName`/`role` live: (a) columns on `platform_user`, or (b) a new `user_profile` table. Either way: nullable, DSAR-wired (G1), `role` as free string from the fixed option list (not an enum migration), email never stored (Clerk-owned).
- **D-4 — The setup composition.** (a) One backend endpoint (proposal: `POST /stage0/setup`, BFF-fronted, `202 {recon_run_id}`) that captures the website artifact, records `onboarding_input`, and invokes `start_recon` — replacing the frontend's proposed `/api/v1/onboarding/setup` 1:1; (b) compose `build_stage0_scrape_binder` at `projections_main` (and `fleet_main`) — closing the CLAUDE.md composition-backlog item (2) for this surface; (c) pick the background-lane driver (inline post-fast re-invoke vs API-root kicker vs fleet job — proposal: API-root post-fast kicker, keeps the request fast and needs no fleet change).
- **D-5 — Progress: Path A (lane-level MVP) vs Path B (granular per-field events).** §4. Proposal: **B** — it is the REQ-08 end-state, the emission change is small and additive, and the founder has twice rejected fake progress; do it now rather than shipping a 2-item checklist and rebuilding.
- **D-6 — Checklist vocabulary.** If B: ratify the item grouping (proposal in §4 Path B: 3 real groups + the dummy brand-kit item per §9; `competitors`/`buyers` items dropped — recon does not do those). The mapping lives in the frontend repository layer as data, not in backend labels.
- **D-7 — Frontend contract amendments.** Retire `GET /api/v1/onboarding` (copy/labels stay in frontend code — serving button copy over HTTP earns nothing); repository grows real methods (`submitProfile`, `startSetup`, `readProgress`/`attachProgress`); all HTTP through the BFF (fixes F1); fixture stays the auth-off/dev default; add the missing exit route from `finalizing` (F3); statuses stop being static (the current frozen checklist violates the no-fake-progress rule even as a *fixture* — it should at least be driven by the fixture repository's simulated event stream, mirroring the chat fixture's pattern).
- **D-8 — Progress transport.** Poll `/stage0/recon/{id}/progress` (+ a new event-cursor read if Path B) vs extending the SSE token mint to recon runs. Proposal: polling for MVP (states are durable; the repository seam hides the transport so SSE can replace it later without component changes) — unless Path B is chosen *and* we want live ticks, in which case extend the mint now (small, well-understood surface).
- **D-9 — Envelope acceptance.** Accept the hardcoded `Stage0Policy` defaults (5¢ fast / 100¢ background / 24h dedupe) for MVP; per-workspace overrides are a later config change. Also decide the provisioning throttle stance (G2) — even "N workspaces per identity per day" suffices for now.

**Sequencing proposal:** slice 1 = D-1 (Clerk screens) + D-2/D-3 (provisioning + profile) — a user can sign up and land in a real workspace with a brand; slice 2 = D-4 (setup composition + binder + driver) with Path-A-level progress; slice 3 = D-5/D-6/D-8 (granular events + honest checklist + transport). Each slice flips only its own repository adapter; fixtures remain for everything undecided.

---

## 9. Ratification log

- **2026-08-12 — founder: brand-kit stays out.** Brand-kit extraction is the design subsystem's share of recon; it is implemented on the parallel design-integration branch and is **not** integrated here. The checklist's brand-kit item is either omitted or rendered as an explicitly-dummy fixture item until that branch merges. (Founder message, this session.)
- **2026-08-12 — founder: no fake progress, explicitly re-affirmed.** Eager recon must emit events granular enough for 1:1 checklist ticks; no fixture-based fake progress in the integrated screens. (Founder message, this session; restates REQ-08's acceptance criterion.)
- **2026-08-12 — founder: onboarding screens are visually frozen; Clerk is headless and authentication-only.** The visual appearance of every onboarding screen must not change at all through integration — the imported components and their approved geometry are the UI. Clerk's role is strictly behind-the-scenes authentication (credential verification + session issuance); it renders nothing and owns nothing beyond auth. This ratifies the visual-fidelity half of D-1; D-1's remaining open items are only the `/sign-in` route disposition and the two fidelity risks (CAPTCHA, email-verification step). (Founder message, this session.)
- **2026-08-12 — founder: D-1 fidelity risks resolved.** (a) **Sign-up CAPTCHA: disabled instance-wide** — no CAPTCHA element mounts anywhere in onboarding. Operator action required in the Clerk dashboard (bot protection off for this instance); implementation must not add the `clerk-captcha` mount node. (b) **Email verification stays on, with a new screen designed in-house**: the verification-code step is added to the flow as a new lightweight screen (code entry), designed by the integrating agent within the frozen visual language — same card geometry, `onboarding.module.css` vocabulary, Satoshi type, `OnboardingHeader`/`OnboardingFooter` framing — as an *addition* to the approved set, not a modification of any approved screen. Step slug proposal: `verify-email`, between `sign-up-email` and `profile`. (Founder message, this session.)
