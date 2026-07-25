# 2026-07-03 — Harness re-platform analysis (founder's platform-level requirement) — PROPOSAL DELIVERED

## What happened
Founder clarified the platform vision: not a linear ABM pipeline but a **deep-agent / harness
platform** — modular capabilities as tools, dynamic workflow order per team, skills-guided agents,
node-based representation for reproducibility — plus 5 hard product requirements (dynamic field
registration; gap/judge loop; research dossier; raw-material ingestion; StorageBackend) and a
conventions complaint (believed the waterfall was re-implemented 3× and shared utils were copied
because of the import contracts). Referenced diagram: `proposed-research-design.png` (DeepAgent
orchestrator → research subsystem → account/contact research with judge-loops + aspect workers over
the claimstore/registry substrate, progress streamed to chat).

Analysis session only — **no code changed**. Deliverables:
- `docs/architecture/clue-hq-harness-replatform-proposal.md` (NEW, uncommitted, marked PROPOSAL) —
  the full design: 4 planes (kernel / toolbelt / orchestration / reproducibility), the 5
  requirements designed onto existing seams, source-planner opening, conventions correction, build
  sequence, decisions table, pre-mortem.
- This note.

## Load-bearing survey findings (5 parallel read-only agents; verified file:line)
- **Waterfall duplication claim REFUTED.** One shared engine `sources/waterfall.py:176–354`;
  stage0 (`stage0/client_kb.py:187`), Pass-A (`discovery_scoring/scoring/engine.py:163`), account
  aspect workers (`profiling/aspect_worker.py:406`) all call it. The single true re-implementation
  is `profiling/contact/fill.py:103–218` — deliberate (per-claim identity_binding must be stamped
  pre-insert; waterfall stamps coarse manifest prior). Fix = `claim_tagger` pre-insert hook on
  `resolve_field`, then contact fill rejoins the engine (−~115 lines).
- **Real DRY debt is the known backlog set** (reference_time ×2, normalize_url/host ×3, jsonb
  scalar decode ×5, manual budget-threading ×3). Root cause: Beat-0 "frozen core" read as
  untouchable → local copies instead of contract-deltas. Import-linter contracts themselves are
  sound (independence = milestone workers; shared services importable by all).
- **Phase order is enforced only by the sequential state machine** (`durable/campaign.py:83–90`);
  handlers don't validate predecessors; out-of-order = **silent empty results** (e.g. DEEP with no
  tier cutoffs → empty high-tier set, `api/deep/handler.py:252`). Tool-ification must convert these
  to loud PreconditionFailed errors. `AccountDeepOrchestrator.run_one` already standalone-ready.
  Confirmed again: inline execution, no detached worker, single-driver unenforced.
- **Source planner is deliberately bounded** (staged-flow §7d config-bounded LLM planning; hard
  allowed-set guard `sources/planner.py:260–275` with off-set audit). Registry is open-by-
  construction with runtime `register_source()` (`sources/registry.py:283`) + `bind_resolver`.
  Missing for agent source-discovery: tier-3 generic web resolver (Firecrawl is tier-2
  target-locked; Exa/Parallel tier-4), a seeded web_search source, a propose→promote path, default
  weight for unprofiled sources. Web up-weighting per (pack, field_class, client) already a config
  knob via source-profile overrides.
- **Field registration**: runtime `register_field()` exists w/ full validation
  (`claimstore/registry.py:207–323`); ICP synthesis silently drops out-of-registry LLM proposals
  (bounds step in `stage0/icp_synthesis.py`). M13.3 `config_revision` proposed→promoted ledger is
  the reusable staging pattern (→ `field_definition_revision`).
- **R2 gap loop**: detection exists (`durable/planning.py:110–137`, waterfall StopReason; M9.5
  stale-claim re-research) but nothing retries never-filled fields, no attempt ledger, no
  unresearchable→review surfacing, no loop closure.
- **R3 dossier**: narrative/handoff/two-sided provenance exist; missing render + derived-claim
  concept (`claim_derivation` side table mirroring `claim_support`; faithfulness judge gains an
  entailment mode).
- **R4 ingestion**: adapters framework exists (pdf/transcription/firecrawl-html/passthrough,
  content-addressed ArtifactCache, ClaimExtractor seam); missing upload endpoint, docx/pptx/OCR
  adapters, durable blob storage, CKB file orchestration.
- **R5 storage**: nothing exists; new uncommitted `config/settings.py` is the config slot.

## Recommendation skeleton (details in the proposal doc)
Keep kernel; expose capabilities as typed, precondition-checked, budgeted, journaled **tools** (two
granularities: campaign ops with engine-owned fan-out; entity/field ops); deep agent + versioned
**skills** (config-as-data via config_revision) + deterministic goal-judge loop; **run-graph
journal + recipes** (current pipeline ships as Recipe #1; outcome-reproducible, not
bit-identical); source planner stays bounded per-call but agent becomes a *registrant* via
propose_source with policy-assigned tiers (≤3 auto, ≥2 human). Iron rule kept: LLM proposes,
engine disposes. Build order: 0 detached worker/lease (unchanged prereq) → 1 StorageBackend → 2
toolbelt façade + loud preconditions + streaming → 3 DRY consolidation (claim_tagger, core
contract-deltas, BudgetTracker, conventions §2 rewrite) → 4 coverage-ledger judge loop +
propose_field/propose_source + generic web resolver + ingestion → 5 run-graph/recipes → 6 agent/
+ skills → 7 dossier + derivation. MCP surface later = adapter over the toolbelt.

## Decisions awaiting founder (see proposal §7)
Agent location (rec: incubate in `agent/` here, lift-out later) · approval posture for proposed
fields/sources · dossier owned here (rec: yes, as view) · replay semantics (rec: outcome-repro) ·
S3-compatible client (rec: yes) · canvas V1 = pin/re-run · prior 2026-06-28 Qs 1/2/4/5 still open
(topology scale, concurrent sessions, replan economics, Stage-0 gate). Q3 now answered: config
edits only through propose→promote ledgers.

## Verification / state
No code or tests touched; working tree still carries the founder's uncommitted M13.3-adjacent
changes (stage0/config/settings.py etc.) — untouched. New files this session: the proposal doc +
this note (both uncommitted; branch `m13.3/learning-loop`).

## Next
Founder reviews proposal → answers §7 decisions → then: ADR + spec updates (M14+ milestones for
toolbelt/harness/recipes), Phase-0 prototype (detached worker + lease), consolidation batch PR.

## Round 2 (same day) — founder follow-ups, answered in proposal §9–§10 (addenda)
Founder accepted the decisions table "mostly sounds good" but raised two pointers before any
build proceeds; both are now designed into the proposal doc as addenda:

1. **Stage 0 must be a dynamic client-understanding conversation, not a rigid sequence** (ask
   about industry/target-industry/ICP needs/signals; use CRM connects; only then research).
   Design (§9): register a `client_interview` **source** (modality=conversation, tier 1 for
   `client.*` — resolver is the chat agent; answers become claims with evidence span = verbatim
   quoted turn, idempotent on (entity, field, turn); faithfulness-judgeable). Client hypotheses
   about market/targets are NOT world-facts → they become `client_stated` signal/field proposals
   (R1). Fixed phase order replaced by a **readiness spec** (config-as-data; coverage/confidence
   floors gating synthesis-worth-running / discovery-spend / deep-spend via existing pre-spend
   machinery); how each gap closes (ask/ingest/CRM/web) is agent-chosen per gap, steered by the
   Stage-0 **skill file** (versioned bundle: frontmatter tool-allowlist + readiness ref + vertical
   overlays + interview-craft prompt body; promoted via config_revision; pinned by recipes).
   Minimum-input preserved (URL-only → flagged assumptions at co-confirm). CKB fill/synthesis/
   co-confirm survive as tools; the fixed sequence dies.

2. **How does agent-native scale to 100–500 accounts with runtime judging + chat glimpse?**
   Design (§10): 500 = queue depth, not 500 chat agents — chat agent is control plane only;
   detached CampaignRunWorker drives a tier-priority queue under a concurrency window (16–32) +
   envelopes + rate limits; per-account M8A graphs execute. **Five-layer quality pyramid:** (1)
   hard determinism every step (caps/envelopes/gates — unbounded wrong-direction generation is
   structurally impossible; unsourced claims unpromotable); (2) per-claim LLM judgment on 100% of
   outputs (M9, exists); (3) per-account goal-judge at round boundaries (R2); (4) **run
   supervisor** (new): deterministic monitors over aggregates (verification health, gap ratio,
   spend-vs-yield, stalls, source errors) + periodic LLM triage; bounded journaled actions
   (quarantine account, trip source breaker, tighten envelope, escalate w/ diagnosis); (5) human =
   exceptions + canary + M13.1 ranked review + samples. Explicitly NOT turn-by-turn LLM
   babysitting (prohibitive + redundant; judge outputs always, trajectories at boundaries,
   aggregates continuously, transcripts by sample). **Canary default in Recipe #1**: top-tier ~10
   → supervisor health gate → open fleet. **Visibility:** projection API (run_overview /
   account_progress / explain_flag; MVCC reads, never interrupts workers) + narrator outbox→SSE
   digests (the diagram's pink note) + steering tools (pause/adjust/kill-source behind confirm
   gates); sessions decoupled from runs (reattach anytime; single-writer lease, prior Q2).

3. **Founder observation adopted as the doc's mental model (§10.4):** the platform is a
   Claude-Code-shaped harness whose "filesystem" is the claim store and whose skills are ABM
   playbooks. Mapping table in doc (agent≈session, toolbelt≈tool registry, skill files≈CLAUDE.md+
   skills, account graphs≈subagents, supervisor+narrator≈background tasks+notifications,
   recipes≈saved workflows, confirm gates≈permission modes, MCP≈MCP). Deliberate divergences:
   typed-claim DB substrate w/ hard domain gates (no vibe-past), durable multi-tenant runs
   outliving sessions, contractual reproducibility (recipes+pinned config+eval floors), no
   reviewer-per-account assumption.

Checked founder's uncommitted diff before answering: config plumbing only (DEFAULT_SYNTHESIS_MODEL
moved out of stage0 into config/settings; gateway/env wiring) — no conflict with the design.
New follow-ups for build plan: interview source + readiness spec → step 4; skill loader (minimal)
may land early for Stage-0; supervisor → step 4/5; narrator SSE → step 2.

## Round 3 (same day) — Stage-0 refinements (founder gained clarity; still DISCUSSION stage)
Founder explicitly flagged we are at **discussion stage** — exchanging opinions, not building.
Accepted the fleet/judging design (layered judging + canary) verbatim. Three Stage-0
clarifications, now designed into proposal §9.4–9.6:

1. **Eager preliminary recon:** at URL+name submission, client reverse-profiling runs in the
   **background** (Recipe #0: same detached worker, small hard envelope, tiers 1–3 + light
   synthesis only — no tier-4 spend before client confirms direction). Two-speed (fast pass =
   own site + officials in seconds-to-minutes; deep pass continues). Output = recon brief
   (mini compose_dossier) + gap list that seeds the interview → agent opens chat with "here's
   what I learned — correct me". Recon and interview never block each other (both write CKB;
   narrator can surface mid-conversation claim arrivals). Discrepancies (recon vs stated) →
   corroborator flags → agent confirms conversationally; tier-1 client-about-self outranks web.
   Guards: domain-keyed dedupe + per-signup envelope; `public_footprint` reuse amortizes recon
   across tenants for the same domain. Recipe #0 doubles as the low-risk first exercise of
   step-0 worker + step-2 projections.
2. **Two-layer client memory:** facts → CKB (structured claim if field exists; else
   `volunteered_statement` record w/ promotion paths → claim or propose_field — nothing dropped
   for lack of registry anticipation). Operating preferences (exclusions, tone, constraints) →
   `client_memory` store read by skills at prompt-assembly, NOT the claim store (instructions ≠
   world-facts); light versioning, each entry carries the creating quote. Analogy: claim store ≈
   codebase; client_memory ≈ CLAUDE.md/auto-memory.
3. **CRM demoted to optional accelerator:** readiness spec must be satisfiable from URL +
   interview + uploads alone (trust barrier: new clients won't OAuth a new platform). Trust-light
   seeds first: name-best-customers in chat (import scenario handles free-text), pasted lists,
   CSV export upload (R4). OAuth CRM offered post-value-proof only.

State: proposal doc + this note updated; still uncommitted; still no code changes. Next: continue
discussion; founder to react to round-3 opinions (recon envelope size, statement-capture UX
posture — implicit-with-visibility recommended, brief format chat-native + artifact).
