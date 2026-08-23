# ARV2 — Account-research rebuild: Apollo + Exa deep-agent plan

> **Revision note (2026-08-23):** after a critical re-evaluation requested by the founder, the
> *phasing* in §8 of this document is superseded by `ARV2-deep-agent-build-runbook.md` (line-by-line
> execution, day-one deliverables, and six recorded revisions — notably: build Exa-only on Day 1,
> touch zero old-lane files, defer Melissa/C7/ICP-compiled-fields out of build scope). The
> no-schema-change position is proven constraint-by-constraint in `ARV2-schema-impact-audit.md`,
> and the Apollo wire schemas (and the repo resolver's incorrect assumed contract) are pinned in
> `ARV2-apollo-api-contract.md`. The provider verdict (§2) and keep/drop treaty (§3) here stand.

**Status:** proposal for founder ratification (Shashank + Aryan). Authored 2026-08-22 from a
five-way repo audit (M8D runtime, claim-store guardrails, provider stack, frontend contracts,
live vendor-API verification) plus the branch-side evidence in
`_memory/2026-08-20-pipeline-guard-inventory.md`, `_memory/2026-08-20-grok-account-run-results.md`,
and `_memory/2026-08-19-live-run-day-close-out.md` on
`origin/platform/comprehensive-account-contact-research`.

**Charter (founder, 2026-08-22):** rebuild account research from scratch — account discovery,
account deep research, buying-committee discovery, contact deep research — to the depth of the
Insight Health dossiers (`digestive-healthcare-of-georgia-p-c.md`, `eagle-physicians-associates-p-a.md`),
as a free-flowing deep-agent system with minimal mechanical guardrails. Keep the claim-store
schema and DB unchanged. Keep the fleet shell unchanged. Evaluate Apollo vs Exa; drop Sumble.
Add MelissaData for direct-mail addresses. Everything lands structured in the claim store and
serves the frontend contracts.

**Aryan's extraction list (2026-08-22 note), honored verbatim:** (1) the claim store — the idea and
flexibility, without the verification guards; (2) the deepagent schema — platform deepagent +
specialized sub-agents; (3) the pack system — core account pack, contact pack, industry packs,
every field class carrying a description the agent reads. Plus: the fleet shell (an orchestrated
worker model the main deepagent dispatches, one real LangGraph agent per account), and the same
agent durability schema so the design subsystem migrates unchanged later.

---

## 1. Ground truth this plan stands on (verified, not assumed)

1. **The live system is `platform/comprehensive-account-contact-research`** (411 commits ahead of
   `main`), not `main`. It already runs: the M8D entity-research fleet (R0–R10), the R11 DEEP-phase
   bridge, a fixed 21-field account profile + 15-field contact profile, prose synthesis
   (`account.summary`, `contact.overview`), the M12.1 value-narrative positioner, committee
   co-definition steering, FI-4 self-serve auth, and the design-substrate Part II slices.
2. **Verification and budget enforcement are already off** on the pilot path
   (`CLUE_PRODUCT_PATH=integration_pilot` forces `verification_enabled=False`,
   `budget_controls_enabled=False`; spend caps are record-only). "Remove the guardrails" is
   therefore **not** the remaining work — most already went.
3. **The 2026-08-20 guard inventory** (five parallel audits, ~500 guards enumerated) found the real
   failure modes: **~20 judgment gates** (LLM/threshold opinions vetoing work — the retire list),
   **~12 correct guards with the wrong failure species** (they suspend the job instead of refusing
   recoverably), **2 kill-switch inversions** (turning verification *off* made typed interview
   values unwritable, and corroboration still blocks field resolution), and harness wedges
   (cross-job settlement folds, checkpoint-replayed poison calls, model-pinned encrypted reasoning).
   The truth/provenance floors and infra guards never once fired wrongly.
4. **The committee blocker is commercial, not technical:** Sumble returns HTTP 402 on `/people` and
   `/techs` — the subscription doesn't cover the endpoints that produce committee members and tech
   stacks. Every live run's empty committee traces to this.
5. **The claim store already admits free-flowing writes.** A claim carrying only
   `(field_key, value_json, source_url, evidence_span-as-quote, confidence)` inserts fine: no
   artifact, no span requirement, no corroboration, no judge. The only mandatory friction is: the
   field must be registered with a matching `value_schema`; `<pack>.*` fields need a resolvable
   `reuse_scope`; `contact.facet.*` needs `identity_binding` + `use_class`. The one **non**-toggleable
   verified-only gate left is the C7 read gate (`research_view_governance.py:317-336`).
6. **An Apollo resolver already exists in the repo** (`resolvers/apollo/`, built as the "direct
   alternative to Clay" reference, unit-tested, unwired; live request shape unverified). So do
   NPI/DUNS/CIK/LEI registry resolvers, ZoomInfo/Clay/BuiltWith stubs, and Parallel/Firecrawl.
   MelissaData is absent (greenfield adapter + pack fields).
7. **The frontend renders new research fields with zero frontend change.** The `/frontend/v1`
   accounts/contacts surface is live (four endpoints; flag `CLUE_FRONTEND_READ_ENABLED`), and
   account `projectSections[].insights|narratives` + `neutralFacts` + contact `professionalFacts`
   render generically off `fieldKey`. New *fields* appear automatically; new *prose* needs prose
   claims (Lane E); the C7 nine-block view has no consumer yet.
8. **Model capability is not the blocker.** The Grok-4.6 forensic note shows the agent executing
   the intended research sequence unprompted and self-repairing from refusals in one turn; the jobs
   died on harness mechanics (pending-ref livelock, replayed poison calls, recursion caps), not on
   research quality.

**Honest implication:** a literal ground-zero rewrite would spend weeks rebuilding the ~380
truth/infra guards that already work and both founders want to keep (claim store, fleet, durable
agent schema, packs). What actually needs rebuilding is the **research lane** — the source stack
(Sumble → Apollo), the tool surface, the field profiles, the guardrail posture, and the failure
semantics. That is what this plan rebuilds, from scratch, as a new lane — and it quarantines the
old lane wholesale, the same pattern M8D-R1 used to retire M8A/M8B/M8C.

---

## 2. Provider verdict: Apollo **and** Exa, in different roles. Sumble out.

The Insight Health dossiers decompose into exactly two species of information:

- **Skeleton** (structured, database-shaped): identity, size, locations, revenue bands,
  technographics, job postings, the committee's names/titles/seniority, emails, direct dials,
  LinkedIn URLs. → **Apollo.**
- **Flesh** (evidence, quotes, judgment): fax-line evidence, prior-auth workload quotes, ownership
  analysis and PE disambiguation, expansion timing signals, career histories, publications, farm
  animals, family legacies, conversation openers — every one cited to a public page. → **Exa +
  the research model.** No contact database sells this; it is open-web research.

They are complements, not competitors. Neither replaces the other.

### Apollo (verified against docs.apollo.io, 2026)

| Capability | Endpoint | Cost |
|---|---|---|
| Account discovery by ICP filters (headcount, location, industry keyword-tags, revenue, ~1,500 technologies, funding, job postings) | `POST /mixed_companies/search` | 1 credit/page (100 results) |
| Org enrichment (firmographics, technographics, funding events, dept headcount + growth, parent/subsidiary hierarchy) | `GET /organizations/enrich` | 1 credit |
| Job postings (hiring-velocity signal) | `GET /organizations/{id}/job_postings` | 1 credit/page |
| Committee skeleton (people by title/seniority at an org — **no emails/phones returned**) | `POST /mixed_people/api_search` | 0 credits |
| Contact enrichment (email ~1 credit; mobile +8 credits, **async via webhook**; GDPR-region personal emails withheld) | `POST /people/match` | 1–9 credits |

Caveats to budget for: master/API keys are effectively gated to higher tiers (confirm with sales);
API enrichment consumes export credits; data quality is LinkedIn-centric — coverage degrades for
small/local businesses (including independent medical practices), titles go stale, and third-party
reports put unverified-email bounce risk at 18–25%. **Consequence:** Apollo output is a *skeleton
the agent verifies*, never autopromoted truth — e.g. a committee candidate from Apollo gets
confirmed against the practice's own site (exactly what the dossiers' "Identity confirmed against
<practice URL>" line does). ZoomInfo stays out (enterprise-gated, ~$50k/yr entry).

### Exa (verified 2026)

The standalone Research API was removed 2026-05-01; deep research is now `POST /search` with
`type: deep | deep-reasoning`, accepting `additionalQueries`, `systemPrompt`, and an
`outputSchema`, returning a synthesized `output` **plus a `grounding` array with field-level
citations and confidence** — a strong match for claim-shaped output. Pricing: search $7/1k,
deep $12/1k, deep-reasoning $15/1k, contents $1/1k pages. Websets (entity discovery with
verification criteria + enrichment columns + monitors) remains available for web-defined ICPs.
**The repo's existing `exa_deep` integration already targets `/search` deep** (`resolvers/exa/deep_contract.py`),
so the wire contract survives.

### The rest of the stack

- **NPI registry (already built, unwired):** free, authoritative, and cited constantly in the
  dossiers (identity + taxonomy + facility confirmation). Wire it as a pack tool for healthcare
  ICPs. DUNS/CIK/LEI ride the same `RegistrySpec` family for other verticals.
- **MelissaData (new adapter):** Business Coder (US business firmographics + address, suite-level
  data, `MelissaEnterpriseKey` as a stable identity anchor) + Global Address Verification
  (CASS-certified, DPV) for the direct-mail path. REST JSON; prepaid credits (~$40/10k, 3P-reported).
  Melissa blocks doc crawlers — confirm per-field DPV output and Business Coder credit cost with a
  trial key before committing.
- **Model:** the dossier bar demands a frontier reasoning model. Whatever is chosen, adopt the
  policy the Grok runs taught: **model identity is part of job identity — relaunch, never resume,
  across a model change** (encrypted-reasoning checkpoints are not portable), and prefer providers
  whose reasoning blocks replay stably.

### Per-account cost envelope (order of magnitude)

Apollo: 1 org enrich + 1 jobs page + people search + ~5–10 email reveals ≈ 8–13 credits.
Exa: ~3–6 deep searches (account narrative, signals, per-contact depth) + a few dozen
search/contents calls ≈ $0.15–$0.50. Melissa: 1–3 credits per mailing address at export time.
Total marginal cost per dossier-grade account: **roughly $1–3** — versus Sumble burning 70–110
credits per committee attempt while returning 402 on the endpoints that mattered.

---

## 3. The treaty: keep / rebuild / delete

### Keep as-is (the extraction list — no rewrites)

1. **Claim store schema + DB.** No migration to the `claim` table. Tier/method columns keep being
   stamped (they are provenance metadata and DB CHECKs reference them) but stop being *routing or
   authority* anywhere in the new lane.
2. **Fleet shell + durable agent schema.** `clue_fleet` (queues, leases, generation fencing,
   heartbeats), the `entity_research_*` tables, `EntityResearchAgentFactory` +
   `AsyncPostgresSaver` checkpointing, and the deepagent turn-durability tables — untouched, so the
   design-subsystem migration path stays identical.
3. **The deepagent anatomy.** Head-of-ABM (deepagents `create_deep_agent`) plans/co-defines/launches;
   entity agents are real LangGraph `create_agent` agents (one per account, per Aryan's note);
   folder-backed versioned prompts/skills/profiles; the operations-manual pattern (v3 proved it).
4. **Packs + field registry.** `register_field` already carries `description`; the pack system
   (core / resonance / facet / committee / industry packs incl. `HEALTHCARE_PRACTICE`) is the
   mechanism for dossier depth. Every ARV2 field ships with an agent-facing description.
5. **Human gates:** product selection, ICP confirmation, discovery approval, launch authority,
   contact selection. These are product, not friction.
6. **Tenancy, append-only triggers, idempotent operation journaling, artifact snapshots, DSAR
   reachability.** Invisible when healthy; they are what make replay and provenance possible.
7. **Frontend contracts** (`/frontend/v1`, the repository seam, generic `fieldKey` rendering) and
   Lane-E prose synthesis + the M12.1 positioner as the serving path.

### Rebuild from scratch (the new lane)

1. **The source stack:** Apollo (productionized), Exa search/contents/deep, NPI registries,
   MelissaData. Static per-field-class ownership; **no waterfall, no tier_plan routing, no
   source-intelligence planner.**
2. **The agent tool surface** (§5): small, direct, freeform-friendly — replacing the
   compiled-bundle `research_account_deep`/`enrich_account`/`discover_buying_committee` machinery
   and its per-field settlement economics.
3. **The field profiles:** the fixed 21/15-field profiles become an **ICP-compiled dossier pack**
   (§6) — core + industry pack + client-qualifier fields synthesized at Stage-0/ICP time.
4. **The guardrail posture** (§7): two real gates + failure-species law, everything else advisory.
5. **Verification as an agent skill,** not an engine phase: the dossiers' own "fabrication audit —
   links opened 11 of 14, items flagged 4" is an *agentic link-check pass*, and that is what ships.

### Delete / quarantine (never carry into the new lane)

1. **The entire Sumble stack** (13 API modules, 5 resolver modules, ~1,783 refs) — quarantined
   behind the R1 pattern (descriptor-stub the tools, freeze the code paths), deleted in the
   already-agreed post-merge cleanup PR. Cancel the Sumble subscription once ARV2's committee path
   is live (founder action).
2. **The ~20 judgment gates** on the guard inventory's retire list (§2 of that note): the interview
   entailment veto + its outage twin + the burned terminal receipt, `_MIN_CONFIDENCE=0.3`, the
   DISCOVERY_SPEND coverage floor, consecutive-zero-yield job kill, the Sumble quality ladder, the
   canary needs-review ratio, Exa waterfall-ordering refusals, category quotas, taxonomy-purity
   suspension, closed enrichment vocabulary, all-criteria-YES buying gates, launch
   override-homogeneity (with drop-the-account semantics).
3. **The two inversions** (they are bugs, not policy): `verification_enabled=False` must make the
   entailment judge a *stamp-skip*, never a refusal; the inline `Corroborator` in
   `sumble_claim_materialization.py` dies with the Sumble stack.
4. **The M4 waterfall, source-tiering config, per-field tier plans as routing, and the six
   still-blocking money guards** flagged in guard-inventory §4 (convert to record-only; the
   highest-value one is the Exa `provider_reported_cost > reserved` quarantine-and-suspend that
   throws away a paid response).

---

## 4. Where the rebuild lives

**Recommendation: this monorepo, new branch `platform/account-research-v2`, cut from
`platform/comprehensive-account-contact-research`.** Reasons:

- Everything on the keep list *lives there in its most advanced state* (R11 bridge, prose fields,
  auth, frontend read layer, the comprehensive-slice fixes). Cutting from `main` would silently
  discard 411 commits of substrate both founders want.
- The monorepo's own charter says the platform grows by adding subsystems behind seams — a fresh
  repo would re-cost auth, tenancy, storage, SSE, fleet, frontend serving, and the durability
  schema for zero product gain. Aryan's "extract three qualities into a new project" is satisfied
  *stronger* by quarantining the old lane in place: the extraction is real, and nothing else is lost.
- The R1 quarantine pattern already proved the "take it down" move safely: the old lane's tools
  become replay-only stubs the moment ARV2's lane is composed; the ~teens of kLOC delete happens in
  the one dedicated cleanup PR after ARV2 is proven live (the trigger condition CLAUDE.md already
  records).

If the founders still prefer a fresh repo after reading the cost, the extraction order is: alembic
schema (claim + entity + fleet + agent tables), `clue_core`, `clue_fleet`, the agent runtime, the
pack system — but plan for 3–4 weeks of re-plumbing before the first research call, versus days on
the branch path.

---

## 5. The ARV2 agent design

### Anatomy (unchanged shape, new muscles)

```
Head-of-ABM deepagent (create_deep_agent)
  ├─ co-defines ICP + committee shape with the user (existing steering, kept)
  ├─ discover_accounts  ──►  Apollo org search (+ Exa Websets for web-defined ICPs)
  ├─ [human approves accounts — existing selection/launch authority]
  └─ launch_account_research ──► fleet shell (unchanged)
        └─ N workers, one LangGraph agent per account (R5 slot, new definition)
              ├─ account dossier research (tools below)
              ├─ committee discovery (Apollo people + web confirmation)
              └─ [human selects contacts] ──► one agent per contact (R7/R8 slot, new definition)
```

### The account agent's tool surface (replaces the 11-tool Sumble/Exa-compiled surface)

| Tool | Backs onto | Notes |
|---|---|---|
| `read_research_state` | claim store + coverage | What is already known; what fields remain. |
| `search_web(query, n)` | Exa `/search` (+ `/contents`) | Unrestricted handy tool — Aryan's explicit ask. |
| `fetch_page(url)` | Exa `/contents` (artifact-captured) | Verbatim quotes; feeds evidence spans + link audit. |
| `research_deep(subject, intent, outputSchema?)` | Exa `/search` `type=deep\|deep-reasoning` | Freeform intent (no 1000-char cap), cited `grounding` back. |
| `apollo_org(domain)` | `/organizations/enrich` (+ job postings) | Skeleton firmographics/technographics/funding/hiring. |
| `apollo_people(titles?, seniority?)` | `/mixed_people/api_search` | Committee skeleton; 0-credit; agent verifies before writing. |
| `apollo_contact(person)` | `/people/match` | Email/phone/LinkedIn (async phone via webhook). |
| `lookup_registry(kind, query)` | NPI (+DUNS/CIK/LEI) per industry pack | Authoritative identity; healthcare = NPI. |
| `write_claims([{field_key, value, source_url, quote, confidence}])` | `insert_claim` | **The one gate** — §7. Bulk; born UNVERIFIED; tier/method stamped mechanically from tool-of-origin. |
| `verify_links(claim_ids?)` | Exa `/contents` batch | The agentic fabrication audit; writes an audit annotation claim per subject. |
| `finalize_research(summary)` | coverage + finalization receipt | Honest-empty is a valid outcome; engine verifies *bookkeeping*, not quality. |

The contact agent mirrors it (minus discovery, plus `verify_address` → Melissa at export time).
`record_committee_role_inferences` survives conceptually as ordinary `write_claims` on committee
fields with the agent's rationale as evidence.

**What deliberately does not exist:** per-field provider settlement folds keyed to jobs (folds key
to `(run, operation)` so replays join settled work — the Grok livelock fix), pre-buy quality
ladders, coverage-ratio stop rules, parallel-wave shape enforcement beyond a max-concurrency cap,
and any LLM judge with veto power.

### Skills (the dossier is the spec)

1. **`account-dossier` skill** — the Insight Health template as method: disqualifiers first
   (EHR-type checks before spend), signals as *quote + meaning-for-pitch + source*, ownership/PE
   disambiguation (the Eagle "different Eagle" trap gets a named subsection), timing signals,
   expansion-path analysis, ad-audience feasibility, "empty is correct; fabrication is the only
   failure."
2. **`committee-discovery` skill** — co-defined plan → Apollo skeleton → per-person identity
   confirmation against a primary source (practice site / NPI / LinkedIn) before the contact
   entity is written; clinical-vs-business classification onto persona keys.
3. **`contact-depth` skill** — career, education, publications (DOI/PubMed links), boards, awards,
   personal hooks by category (hometown / alma mater / hobby / pet / family milestone / faith /
   recent post) each with verbatim quote + source, conversation openers derived only from written
   hooks, sensitivity marking (§7).
4. **`fabrication-audit` skill** — open every cited link, flag broken/misquoted items, write the
   audit annotation. Mirrors the dossiers' audit block verbatim.
5. **The operations manual** (v3 pattern) regenerated for the new surface — every refusal code the
   new lane can emit gets a taught reaction; the R10 test that asserts manual-covers-every-code
   comes along.

---

## 6. Data model: the dossier as an ICP-compiled pack

The fixed 21-field profile is the wrong shape for dossier depth — the dossier's most valuable
fields are **client-specific qualifiers** (runs-Epic-not-gGastro, owns-ASCs, fax-based-referrals).
ARV2 replaces the fixed profile with a pack stack compiled at ICP time:

1. **Core account pack** (exists): identity, size, locations, revenue, tech stack, funding, hiring.
2. **Industry pack** (exists; `HEALTHCARE_PRACTICE` already defined): NPI, facility taxonomy, EHR
   vendor, provider counts, payer mix… — registered fields with descriptions, tier-1 registry
   sources wired where they exist.
3. **Client qualifier fields** (new mechanism, existing registry): at ICP confirmation, Stage-0
   compiles the client's disqualifiers/qualifiers into registered `<pack>.*` fields with
   descriptions and `reuse_scope` declared (e.g. `gi.ehr_vendor`, `gi.runs_ggastro`,
   `gi.owned_asc_count`, `gi.referral_intake_mode`). The deepagent proposes them; the human
   confirms them with the ICP. This is what makes "the deepest research possible on all the things
   that are needed" *client-shaped* instead of hardcoded.
4. **Signals** (exist: `account.operational_pain`, `account.strategic_moves`,
   `account.resonance.*`) — each signal claim carries the verbatim quote as its evidence span, the
   meaning-for-pitch in the value, the URL as source. Identical to the dossier's signal bullets.
5. **Contact facets** (exist, 9 registered) + additions: `contact.facet.awards`,
   `contact.facet.board_roles`, `contact.facet.memberships`, `contact.facet.openers`,
   `contact.channel.postal_address` (Melissa-verified, for direct mail), plus the audit annotation
   field per subject.
6. **Prose + narrative** (exist): `account.summary` / `contact.overview` (Lane E) and the
   per-persona value narrative (M12.1) — the "Why This Account Is A Strong Fit" and "How To
   Position The Outreach" sections respectively.

Serving needs zero frontend work for facts (generic `fieldKey` rendering); prose lands as prose
claims; the C7 nine-block dossier view becomes consumable after the one-line governance change (§7).

---

## 7. The guardrail charter (the "one or two", and the law of failure)

**Gate 1 — the write gate (`write_claims`).** Field registered + value matches `value_schema` +
`source_url` present + facet claims carry binding/use-class. On refusal the tool returns, as a
normal tool message: the exact field, the exact violation, and the corrective shape. It never
raises, never kills a turn, never burns a terminal receipt. (This is `check_claim_writable`
surfaced properly — it already produces actionable messages.)

**Gate 2 — human authority.** Product/ICP confirmation, discovery approval, launch, contact
selection. Unchanged.

**Everything else is advisory or bookkeeping.** Coverage assessment advises; judges (if ever run)
annotate; spend records; provenance stamps.

**The law of failure species** (from the guard inventory, now a design rule of the lane):

1. A model-input failure is a **recoverable tool refusal** — always, including on checkpoint
   resume. A resumed job replays its poison call **through the refusal renderer**, so the
   corrective guidance reaches the model instead of re-dying (the Grok root-cause-#2 fix).
2. A raw exception escaping to the supervisor is a defect by definition. Unknown failure →
   paused-resumable with the reason surfaced, never terminal.
3. Zero yield is an honest outcome, never a job-killer. Recursion/tool caps push to finalize with
   honest coverage, never raise.
4. Settlement folds are run-scoped, so replayed operations join settled work instead of pending
   forever (Grok root-cause #1).
5. Judgment (quality opinions, thresholds, ratios) may **annotate but never veto**.
6. Money truth still blocks (4xx folds, unknown-spend quarantine, anti-double-spend); money *caps*
   record only.

**Two kept verification floors, because they are product, not friction:**

- **Provenance floor:** every claim carries source + (for quotes) the verbatim span. This is what
  makes the dossier's "every fact has a source link" promise structural. It is a *write shape*,
  not a gate — nothing corroborates, judges, or blocks on it.
- **The use gate for personal data** (`SENSITIVE` never usable for outreach — hard floor). The
  dossiers contain faith and family-history hooks; ARV2 *records* them as facet claims with
  `use_class` stamped, and the outreach layer decides usability. Research depth and outreach
  appropriateness stay separate decisions — this is the one guardrail whose absence can hurt a
  client in public, and it costs nothing at research time.

**One-line unlocks to schedule with the lane:** make the C7 read gate toggle-aware
(`research_view_governance.py:327` treats UNVERIFIED as servable when `verification_enabled=False`),
and fix inversion 1 (judge-off ⇒ stamp-skip, not refusal) so Stage-0 typed values write again.

---

## 8. Build phases (each ends green + a live browser gate, per house discipline)

**Phase 0 — ratify + procure (founders, this week).**
Ratify this plan (esp. §3 deletes, §4 branch, §7 charter). Buy: Apollo plan with API/master key +
export credits (confirm API tier with sales); Melissa trial key; pick the research model. Decide
Sumble cancellation date. Rule on the two inversions + C7 gate (recommended: fix all three).

**Phase 1 — providers (independent, parallelizable).**
Productionize the Apollo resolver against recorded live fixtures (org search / org enrich / job
postings / people search / people match + webhook receiver for phones). Wire NPI. Build the
Melissa adapter (Business Coder + address verify) + `contact.channel.postal_address` field. Keep
the snapshot/artifact persistence pattern (acquire → persist raw → materialize from snapshot) —
it is what makes replay and evidence work, and it is not a guardrail.

**Phase 2 — the account agent v2.**
New R5 definition (profile/prompt/skills/manual v1 of the ARV2 catalog), the §5 tool surface,
`write_claims` + `verify_links`, run-scoped settlement, the failure-species law implemented in the
runtime wiring (refusal-rendered replay, no raw raises, caps-push-to-finalize). Retire the §3
judgment gates *on this lane* (the old lane is quarantined, not edited). Exit gate: one real
account (use Digestive Healthcare of Georgia as the acceptance fixture — the dossier is the
answer key) researched end-to-end to dossier depth, claims visible in the account detail screen.

**Phase 3 — committee + contact agent v2.**
Apollo-backed committee discovery behind the co-defined plan; per-person identity confirmation;
contact agent with the `contact-depth` + `fabrication-audit` skills; email/phone enrichment.
Exit gate: the Eagle Physicians committee (President, GI Division Chief, COO, VP, Referral
Director analogues) discovered, confirmed, deep-researched, rendered in the committee panel and
contact profile.

**Phase 4 — discovery + fleet scale.**
`discover_accounts` via Apollo org search (+ Websets path kept for web-defined ICPs); approval
flow; fleet fan-out over an approved cohort (the R6/R9 shell as-is); ICP-compiled qualifier
fields (§6.3) landing at Stage-0.

**Phase 5 — serving + export.**
C7 governance one-liner; prose + value-narrative over ARV2 claims; dossier view/export (the C7
snapshot machinery already exists); Melissa address verification on the direct-mail export path;
frontend parity re-audit against the clue-frontend design truth (founder's standing complaint —
strict-visual-parity rule already ratified 2026-08-18).

**Phase 6 — the cleanup PR.**
After ARV2 has run in anger: the one dedicated stub-and-delete PR for the Sumble stack + the
quarantined old research lane + dead judgment-gate code, per the trigger condition already in
CLAUDE.md.

---

## 9. Open decisions for the founders

1. **Branch base** — §4 recommends cutting from `platform/comprehensive-account-contact-research`.
   Needs both founders (it is Aryan's live branch).
2. **Apollo plan tier** — API key + export-credit volume; confirm master-key availability and the
   contractual position on storing revealed emails/phones.
3. **Sumble cancellation date** — after Phase 3's exit gate, recommended.
4. **Research model** + relaunch-over-resume ruling for model changes.
5. **Melissa product mix** — Business Coder vs Global Address Verification vs both; needs a trial
   key to confirm DPV output and per-record cost (their docs block crawlers).
6. **The §7 rulings** — the two inversions, the C7 gate, and the six still-blocking money guards
   → record-only.
7. **Sensitive-hook posture** — confirm the hard floor stays (recorded-but-never-outreach for
   `SENSITIVE`), or define a client-facing toggle with counsel.
8. **Old-lane disposition** — quarantine now / delete in Phase 6 (recommended), vs delete
   immediately (slower, riskier, no product gain).
