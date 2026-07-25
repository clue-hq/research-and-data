# 2026-07-06 — Co-founder plan pack (~/Downloads/plan) vs research-subsystem thought process

## What happened
Founder attached the harness-discussion transcript and asked for a close read of the co-founder's
(Shank's) 13-doc product/frontend plan pack at `~/Downloads/plan`, comparing it against the
conversation to date (harness replatform proposal §1–§10, rounds 1–3) and this repo's architecture.
Analysis session only — no code changed, nothing in `~/Downloads/plan` modified.

## The pack (read in full)
`00-master-plan` (Six Locks, division of labor: Shank frontend, Aryan backend/agents, treaty =
`08-backend-contract.md`), `01-product-strategy`, `02-object-model-memory` (dossier block grammar,
AccountSchema, memory system), `03-experience-architecture`, `04-screens-prd`, `06-nodes-artifacts`
(canvas node specs incl. research nodes), `07-frontend-architecture` (builds 100% on MSW mocks of
the treaty), `08-backend-contract` (THE TREATY: entities/endpoints/SSE, additive-only, mock-parity,
ends with a "Treaty Review Agenda" for Aryan), `09-analytics`, `10-agents-skills-catalog`
(Head-of-ABM supervisor, 33 skills, recipes, quality modes), `11-build-plan-tickets` (88 frontend
tickets), `backend-reference` (non-binding v1 sketch). Calibration fixture = Eagle Physicians
dossier; golden path = Benchling 10-account pilot.

## Verdict delivered
No platform-direction conflict — the pack IS the harness pivot at platform level (supervisor +
typed skills + recipes + constrained composition + canvas + gates ≈ proposal planes 2–4; "registry
only, type-validated, gate closure, costed, canvas approval" ≈ "LLM proposes, engine disposes").
It also decides open Q "agent location": platform-level Head-of-ABM owns planning; this repo
becomes the research capability provider behind the treaty. Convergent-by-fixture on research
values (omission over fabrication, per-fact source+verbatim quote, negative findings stored).

## Major mismatches flagged (ranked)
1. **Two-pass inversion**: `full-campaign` recipe runs enrich → deep dossier ($3–8) → verify →
   fit.score(reads verified dossier) → tier_recommendation, uniformly per account; tier gates
   package richness, not research depth. Direct conflict with "never uniform deep research" /
   Pass-A→tier-checkpoint→Pass-B. Fix: provisional fit from enrichment (FitModel already weights
   schema variables), tier gate before dossier.research; final score from dossier.
2. **Stage-0**: Lock 6 = single-pass brief, "confirm once", "no second ingestion pass" vs rounds
   2–3 governed interview + readiness spec + interview-as-source + ICP re-synthesis. Recon
   converges; the interview loop has no surface in the pack.
3. **Truth inversion**: dossier = versioned truth *document* (claims are blocks inside it;
   EvidencePack transient) vs claim store substrate + dossier-as-view. Mostly mappable (02 says
   Aryan owns storage) except two leaks: memory `kind:"fact"` at account scope duplicates claim
   truth (dual-truth risk; transcript said facts→CKB, prefs→memory), and ICP lives as brand object
   + memory seeds, not versioned spec.
4. **Verification as pipeline step/dial**: claim.verify node post-synthesis; Draft mode = "link-
   alive check only"; hard-block physical only. vs verification-as-substrate (born provenance,
   faithfulness at write, pre-spend gates, mode-independent promotion bar). Treaty
   `verified:boolean` + method enum too thin for verdicts/conflicts/binding/use-class.
5. **Personal-data governance thin**: `use_with_care` two-level flag + cringe.check vs Doc D
   (jurisdiction switch, use-classes, sensitive-excluded-default, retention, DSAR). Fixtures
   celebrate faith/Holocaust-family hooks — excluded under repo default posture. Reconcilable as
   "strict, switched down to US-permissive w/ per-use human confirm" but pack has no jurisdiction
   concept, no DSAR surface.
6. **Contract deltas the repo must grow**: per-product FitScore (account×product, 72/68/40
   fixture bar) + qualifiers; per-workspace contact_class vocabulary (clinical/business) alongside
   committee personas; millicredit ledger w/ holds; run-manifest PATCH ops + expected_seq; SSE
   vocabulary + replay; timeline_phase emission; quality modes → knob mapping (never the promotion
   bar).
7. **Additive gaps**: no M13.1-style verification review queue kind; no coverage/attempt-ledger
   surface ("tried X over N rounds"); no docx/pptx→claims ingestion endpoint (composer Upload is
   the hook); no mid-research propose_field; no source-tier/yield observability.
8. Minor: pack says Aryan = "Rust + LangGraph" (repo is Python); question-set-per-campaign vs
   per-account gap planning (internals, fine); 02 confidence high/med/low vs 08 numeric 0–1
   (pack-internal inconsistency, treaty agenda item).

## Follow-ups
- Treaty review pass (00 §8 open item): bring items 1–7 above as additions to 08's own Review
  Agenda; decide dossier-block projection contract over claims; decide memory-fact vs claim rule.
- Lock 6 conversation: "one ingestion pass" (fine, = recon dedupe) vs "client understanding done
  after one confirm" (conflicts with interview design).
- No code work started; branch `m13.3/learning-loop` untouched this session.

## Round 2 (same day) — founder DECISIONS on all five mismatches; additive-gaps plan recorded
Founder resolved every flagged mismatch (with 3 onboarding-flow sketches attached). Recorded as
**§11 of `docs/architecture/clue-hq-harness-replatform-proposal.md`** (addendum pattern, like
§9/§10; doc still uncommitted). Standing rule: **nothing already planned in this subsystem is
deleted or weakened — all frontend-driven work is additive.**

1. **Two-pass**: our principle prevails (Pass A → tier checkpoint → Pass B). Recipe spine to be
   corrected at treaty review; per-product fit becomes two-stage (provisional from Pass-A
   enrichment via FitModel schema-variable weights; final evidence-linked score post-deep).
2. **Stage 0 stands unchanged** (recon Recipe #0 + interview-as-source + readiness spec + ICP
   re-synthesis) — "frontend docs slightly misunderstood." Lock 6 = one *scrape* pass only.
   Additive flow adopted (§11.2): URL → ingestion w/ real event ticks (website scrape, KB scrape,
   brand guide, brand voice, ICP intent, value-prop → brand "theme complete") → "How do you wanna
   get started" fork (**"Surprise me"** = recon brief + gap list + candidate accounts + negative
   winners projected as a card = discovery entry; **"I know my account"** = named targets =
   import entry) → both land in chat, where the interview-as-source runs directly.
3. (Merged into 2.)
4. **Verification**: substrate unchanged; the pack's `claim.verify`/`fabrication.audit` node is
   an additive visible re-check surface. Quality modes vary breadth/variants/corroboration —
   never the promotion bar.
5. **Compliance**: M10/Doc D exactly as planned, no compromise; the pack's `use_with_care` flag
   becomes a projection of use-class + client posture; frontend is a skin, still in process.

Additive-gaps plan (proposal §11.3–11.4, delete-nothing): Group A (serving surfaces) — dossier
block projection (9-block vocab over claims, R3), per-product FitScore (account×product) +
tier_recommendation, registered contact_class vocabulary beside committee personas, run-manifest
projection + PATCH ops w/ expected_seq, SSE per treaty §5 (replay/tokens/topics), timeline_phase
emission, millicredit ledger w/ holds over the USD ledger, quality-mode→knob mapping (invariants
untouchable), HTTP Idempotency-Key store, batch re-verification tool + fabrication-audit rollups.
Group B (additive treaty PRs) — richer verification fields (tier/conflict/faithfulness/binding/
use-class beside `verified:boolean`), verification-review queue kind (M13.1/M13.2), coverage &
gaps surface (R2 attempt ledger), compliance surfaces reserved (jurisdiction config, use-class on
wire, DSAR), ingestion endpoints (R4), propose_field/propose_source surfacing, recipe-spine tier
gate correction. Build-sequence placement mapped in §11.4 (steps 0–7 unchanged; additions slot
into steps 2, 4, 7 + scoring/committee seams).

State: proposal §11 + this note updated; both still uncommitted (established review convention);
no code changes. Next: turn §11.3 Group B into concrete treaty PRs at the first treaty-review
pass with Shank; then §6 build steps proceed as ordered with the slotted additions.

## Round 3 (same day) — consolidated architecture & requirements doc written
Founder asked for a detailed, complete documentation of the new architecture + requirements.
Created **`docs/architecture/clue-hq-harness-architecture-and-requirements.md`** (v1.0, marked
CONFIRMED design record) — consolidates proposal §1–§11 + all founder decisions into:
- Part I: context (platform, division of labor, what changed vs. what didn't) + inherited
  invariants (four outputs, D1 boundary w/ block projection, core bet, principles, the
  authority-boundary table for "LLM proposes, engine disposes").
- Part II: **17 requirements** (REQ-01 non-linear harness … REQ-17 treaty evolution), each with
  rationale / design / current-state delta / plan step / acceptance criteria. REQ-13/14/15 encode
  the 2026-07-06 decisions (two-stage per-product fit, verification substrate + additive re-check,
  M10 no-compromise).
- Part III: four planes in detail, data/config-model additions table, runtime topology diagram,
  external interfaces, the confirmed Stage-0 end-to-end walkthrough (incl. the sketched
  ingestion-ticks → fork → chat flow).
- Part IV: build sequence 0–7 with slotted additions + de-risk tests, decisions register
  (resolved + open O1–O8 w/ working defaults), pre-mortem (9 guards incl. dual-truth and
  quality-mode-erosion), non-goals, cross-reference map.
Authority note: this doc is authoritative for the harness era; proposal doc remains the
analysis/evidence trail; original doc set remains authoritative for the substrate.
Open items surfaced for founder: commit posture for the 3 uncommitted docs; whether Recipe #0
includes a cheap candidate-account preview pre-ICP-confirm (the "Surprise me" card shows
"possible accounts to reach"); confirm O4–O6 working defaults; product-entity modeling for
per-product fit (products as client.* CKB entities vs. platform-side only).
