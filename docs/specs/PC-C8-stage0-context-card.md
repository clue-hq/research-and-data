# PC-C8 — The Stage-0 project card: one owner per concern for L3

**Status:** DRAFT **v2** for review — no code has been changed against this spec.
**v2 changelog (2026-08-01):** incorporates the six blockers + corrections from the second review round, all independently verified against the code before adoption. Major deltas from v1: (a) **errata** — v1 falsely claimed `clue_projections/stage0.py` did not exist and called the original proposal's citation fabricated; the file exists (commit `08c1998`) and v1's claim was an artifact of a truncated `ls | head` — this slice *extends* that module; (b) `current_turn_input` **removed from the card** — turn identity is L7/engine-side, not project state; (c) the card gets a **hard, deterministic size policy**; (d) trial restrictions move to the **capability surface**, not the shared skill; (e) the compiler gets an explicit **evidence-reader port**; (f) ICP proposals: **confirmed-only** in the card; (g) **DSAR erasure for card copies is in-slice**, not deferred; (h) readiness selection reuses `stage0_readiness`'s override/lineage logic.
**Parent finding:** the 2026-08-01 L3 context-budget failure (`required l3_project context exceeds its hard layer budget`, `context.py:579`) on `trial-63553478967758a6`; byte-level audit in §11.
**Doc authority:** implements Doc A Part III — L3 is specified there as a *"Project state card ... [from the] projection API"*; the current implementation violates that contract. This spec is drift correction, not new architecture.
**Scope:** Slice 1 only. Identity single-injection, required-first budget ordering, and the tokenizer swap are Slice 2; long-lived Recipe #0 is Slice 3 (needs its own design ruling); report-export/KB-refresh conditioning is Slice 4.

---

## 1. The defect being fixed (evidence)

At the failing turn, L3's three **required** artifacts measured against the 48,000-byte budget (`stage0_trial.py:398–412`):

| Required L3 item | Bytes | Written at |
|---|---|---|
| stage snapshot | 32,178 | `stage0_trial.py:729` |
| readiness snapshot | 15,889 | `stage0_trial.py:756` |
| budget envelope | 140 | `stage0_trial.py:766` |
| **Total** | **48,207** | hard-fails at `context.py:578` |

Root causes, each owned somewhere in this spec:

1. **Raw-row payloads.** `snapshot()` ships `SELECT to_jsonb(s) FROM volunteered_statement` / `to_jsonb(r) FROM readiness_decision` (`stage0_trial.py:1287,1297`) to the model — every column, nulls, UUIDs, hashes. A statement row carries **zero bytes of the quoted text** (offsets + sha only): oversized and unreadable at once. → §3–§4.
2. **Verbatim duplication.** The stage artifact embeds `current_truth` including `readiness_decisions` (`:750`); the readiness artifact serializes the same list again (`:760`). ~16KB — a third of the budget — is the same data twice. → §3, §5.
3. **Unbounded required growth.** `_recompute_readiness` (`:927`) appends an ~878 B decision row per material turn — serialized **twice** (~1.76 KB) — and each routed statement adds ~690 B more; the snapshot always carries the whole ledger. Required L3 grows **≈2.4 KB per material turn** regardless of message content (the Slice-0 fixture independently measures ≈2.3 KB/turn). Note: the 48,207 B cliff is a function of ledger length **× row content**, not a fixed "~20 turns" — synthetic rows at the historical 20-statement/18-decision shape measure *under* budget (~45.4 KB); the failing run's fatter ids/route-keys/metrics crossed it earlier. → §3 (size policy), §7 (history via tools).
4. **The model round-trips trusted identity and the full answer body.** `RecordInterviewAnswerInput` (`stage0_tools.py:286`) requires the model to author `onboarding_input_id`, `artifact_key`, and the byte-identical `answer` — while `project_id` on the same input is already engine-injected ("supplied by the platform, never by you"). → §6.

---

## 2. Rulings

1. **L3 carries one project-state projection plus one separately-owned budget-authority envelope.** The `Stage0ProjectCard` is a hard-bounded projection of *current effective project state* compiled by the projection layer. The budget envelope stays its own constitution field and L3 candidate: it is spend **authority**, consumed by delegation (`specialist_wiring.py:364`, `agent_execution_wiring.py:1011,1780`), and authority artifacts do not share an owner with context projections.
2. **The card is hard-bounded current project state — never a container for current-turn authority.** Turn-scoped identity lives at L7 and the execution seam (§6). (v1 put `current_turn_input` in the card; that both violated the layer model and defeated content-addressed card reuse, since the card would have changed every turn.)
3. **The model classifies the turn; the engine supplies the captured bytes and trusted identifiers.** Extends the existing constitution-injection seam (the "2b" mechanism) rather than inventing one.
4. **Trial restrictions are enforced by the trial capability surface, not by prose in the shared skill.** A prompt saying "do not call it" is guidance; governance is a tool that is not installed. (This platform's own no-fake-agency principle applied to itself.)
5. **History stays durable and reachable through bounded governed tools, never resident in the opening prompt.**

---

## 3. The card schema (`application/vnd.clue.stage0-project-card+json`)

```jsonc
{
  "schema_version": "1",
  "card_kind": "stage0_project",
  "compiler_policy_version": "stage0-card-policy-v1",   // the §3.1 caps are versioned policy

  // -- identity frame (compiled once, never repeated per row) --
  "project": { "project_id": "prj_…", "name": "neuro-abm", "workspace_id": "…", "brand_id": "brd_…" },
  "product": { "product_id": "prd_…", "name": "Aura AI", "confirmed": true },

  // -- the legal claim-field allowlist (today stage0_trial.py:749) --
  "registered_client_claim_fields": ["client.product.description", "…"],

  // -- client knowledge: bounded briefs + refs, never full claim dumps --
  "client_knowledge": {
    "version": 1,
    "known_fields": [
      { "field": "client.product.description", "brief_value": "…", "claim_id": "…" }
    ],
    "open_gaps": ["…"]
  },

  // -- interview: bounded CURRENT EFFECTIVE statements, with readable quotes --
  "interview": {
    "current_effective_statements": [
      {
        "statement_id": "…",
        "route_key": "campaign_goal_and_target_scope",
        "route_kind": "project_state",
        "quoted_text": "I want to run and start with an ABM campaign selling…",
        "quote_truncated": false,
        "supersedes": null
      }
    ],
    "selection": {                       // honesty about the bound (see §3.1)
      "included": 32,
      "total_effective": 57,
      "order": "dedup_supersession_newest_first",
      "cursor": "…"                      // pagination cursor for the inspection tool
    },
    "unmapped_count": 3,
    "superseded_count": 4
  },

  // -- readiness: latest AUTHORITATIVE decision per gate for the CURRENT lineage --
  "readiness": {
    "latest_by_gate": [
      {
        "gate": "icp_synthesis",
        "decision_id": "…",
        "verdict": "not_ready",
        "effective_verdict": "overridden",      // reuses stage0_readiness's override logic
        "override_ref": "…",
        "decision_lineage": {
          "client_kb_version": 1,
          "product_id": "prd_…",
          "icp_key": null,
          "icp_version": null,
          "spec_version": 1
        },
        "metrics": { "project_state_statements": 9, "verified_claims": 0 },
        "reason_codes": []
      }
    ],
    "ledger_length": 18
  },

  // -- ICP: confirmed refs + staleness ONLY (Blocker-5 option 3; see §5.1) --
  "icp": {
    "confirmed": [ { "icp_key": "…", "version": 1 } ],
    "proposals_pending": true,           // boolean + staleness, no proposal bodies
    "proposals_stale": false
  },

  // -- bounded, typed omission surface: kinds + counts + cursors, NO tool names --
  "omissions": [
    { "kind": "statements_over_cap", "count": 25, "cursor": "…" },
    { "kind": "excluded_statement_evidence_missing", "count": 1, "cursor": "…" },
    { "kind": "readiness_history", "count": 17, "cursor": "…" }
  ],

  // -- compile lineage (no invented fields — Project has no version column,
  //    clue_spine/spine.py:87) --
  "compiled_from": {
    "client_kb_version": 1,
    "statement_selection_digest": "sha256:…",   // canonical digest of included statement ids
    "readiness_decision_ids": ["…"],
    "confirmed_icps": [ { "icp_key": "…", "version": 1 } ],
    "compiler_policy_version": "stage0-card-policy-v1"
  }
}
```

**Never in the card:** full DB rows; the readiness ledger; per-row repeated tenancy ids; null fields (`exclude_none` canonical JSON); timestamps irrelevant to reasoning; hashes the model doesn't consume; behavioral instructions (§8); proposal bodies (§5.1); current-turn identity (§6); tool names (`omissions` carries typed kinds + cursors; the resource manifest owns the effective tool surface, so the card can never advertise a tool the profile doesn't install).

**Determinism:** canonical JSON (sorted keys, no NaN, `ensure_ascii=False` — the `_canonical_json` discipline, `account_research_turn_wiring.py:150`). Same durable state + same policy version ⇒ byte-identical card ⇒ same sha256 ⇒ content-addressed dedup and deterministic context receipts. Because turn identity is out of the card (§6), an unchanged project state across turns now genuinely re-uses the same card artifact.

### 3.1 The card size policy (hard, deterministic, versioned — Blocker 1)

"Current effective statements" alone does not bound the card: a broad conversation accumulates non-superseded statements linearly. The bound is explicit policy (`stage0-card-policy-v1`), enforced in the compiler and asserted in tests:

| Dimension | Cap (v1 defaults) | On overflow |
|---|---|---|
| effective statements included | **40** (aligned with `MAX_PROJECT_STATEMENTS = 40`, `icp_synthesis.py` — one number, one rationale) | deterministic selection: dedup exact `(route_key, quote)` → drop superseded → newest-first; `omissions[kind=statements_over_cap]` with count + cursor |
| single `quoted_text` | 1,000 bytes | truncate at a UTF-8 boundary, `quote_truncated: true`; full text via inspection tool |
| aggregate quoted text | 16,000 bytes | reduce statement count below 40 until it fits (newest-first survives) |
| single KB `brief_value` | 256 bytes | truncate with marker; full claim via claim ref |
| KB `known_fields` aggregate | 4,000 bytes | field-registry order, overflow to omissions |
| `omissions` entries | 12 entries; counts + one cursor each, **never id lists** | collapse to a single `omissions_truncated` entry |
| **whole serialized card** | **24,000 bytes, asserted in tests** | compile-time invariant violation = bug, not a runtime path |

Selection order, priorities, and caps are data (policy-is-data), versioned via `compiler_policy_version`, which participates in the card bytes — a policy change is a visible card change. Slice 2 converts the *layer budget* to model tokens; these *content* caps stay byte-denominated (they bound storage and serialization, not tokenization).

Size arithmetic: 40 statements × ≤(1,000 quote + ~120 envelope) bounded by the 16,000 aggregate ⇒ interview ≤ ~21KB worst case, typical ~5KB; card cap 24,000 + budget envelope 140 sits at half the 48,000 L3 budget even in the worst case. AC-1 becomes enforceable: the card cannot exceed 24,000 bytes at any ledger size, by construction.

---

## 4. The projection module (brownfield — extends `clue_projections/stage0.py`)

**Erratum (v1):** v1 claimed this module did not exist and called the prior proposal's citation fabricated. **Wrong** — `platform/projections/clue_projections/stage0.py` exists (commit `08c1998`) and already owns `ReconBriefView`, `Stage0ProgressView`, `Stage0ReadinessView`, `recon_brief`, `stage0_progress`, `stage0_readiness`. This slice **extends** it.

Additions:

- **`Stage0ProjectCard`** (frozen Pydantic model, same idiom as the sibling views) + **`compile_stage0_project_card(...)`**.
- **Readiness selection reuses, not re-derives:** "latest authoritative decision per gate" is defined as — latest `created_by_actor='system'` decision whose `decision_lineage` matches the *current* pinned lineage (current `client_kb_version`, current `product_id`, current confirmed ICP `(key, version)` if any, current `spec_version`), with any valid human override applied via the same `readiness_override` join `stage0_readiness` already implements (`stage0.py:148–161`). A gate with no lineage-current decision appears with `verdict: "not_evaluated_for_current_lineage"` rather than silently showing a stale verdict. Extract the shared override/lineage helper from `stage0_readiness` so the two surfaces cannot drift.
- **The evidence-reader port (Blocker 4).** A `conn` alone cannot resolve quotes — that requires artifact bytes, sha verification, and offset slicing (today done via `DurableAgentArtifactStore` inside `stage0_trial.py:1148–1220`). The projection declares a protocol and the api composition root injects the artifact-backed implementation:

```python
class StatementEvidenceReader(Protocol):
    async def resolve_quote(
        self, *, workspace_id: str, statement: VolunteeredStatementRow,
    ) -> ResolvedQuote | ExcludedEvidence: ...
```

  The implementation owns: workspace validation; missing/tombstoned evidence (→ `ExcludedEvidence`, surfaced in `omissions`, never silently dropped); content-sha and quote-sha verification; UTF-8 offset semantics; bounded reads. **This is the DRY seam** — ICP synthesis's `_project_statements` logic migrates onto the same port (follow-up noted in §10 task 1.1) so synthesis and the card can never disagree about what a statement says.
- **Import legality:** `clue_projections` already imports `clue_research.stage0` read functions (`stage0.py:10`) and sits below the api root; the port keeps artifact I/O inverted. No agent-package imports.

`snapshot()` (`stage0_trial.py:1250`) **remains** for the human `/report`/`/status` surfaces — full-fidelity inspection is its correct job. It stops feeding model context.

### 5.1 ICP proposal source (Blocker 5 — decided: option 3)

Unconfirmed proposal state lives in trial-local `.context` files (`_read_icp_proposals`, `stage0_trial.py:1317`) — not a legal projection source. The card therefore carries **confirmed ICP refs + `proposals_pending`/`proposals_stale` booleans only**. Proposal bodies stay on the human surface (`/synthesize-icp` output, report bundle), which is where confirmation decisions are made anyway. If a future slice persists proposals durably, the card can grow proposal *refs* through the normal schema-version path.

---

## 6. Current-turn authority: L7 + the execution seam (Blocker 2)

Turn identity leaves the card entirely. Two coordinated changes:

**(a) Engine-side binding (preferred, in-slice).** Extend the existing trusted-injection seam — the same mechanism that already injects `project_id` ("supplied by the platform, never by you", `stage0_tools.py`) — to cover the turn:

```text
Model authors:                      Engine injects at the execution seam:
- route_kind / route_key            - onboarding_input_id
- quote_start / quote_end           - artifact_key
- correction lineage                - the exact captured answer body (loaded from the artifact)
- proposed typed value              - workspace/project/product/client authority
```

The governed wrapper loads the captured answer from the artifact store, applies the model's offsets against those exact bytes, and verifies quotes there. This removes: the byte-identical `answer` round-trip (and its retyping/hash-failure class), trusted ids from model authorship, and turn authority from L3. `RecordInterviewAnswerInput`'s model-facing schema shrinks accordingly (authority fields move behind the boundary, same filtering mechanism as 2b); the F8 prevention-gate mapping and field descriptions update in the same commit; this rides the **same** profile/schema version bump as §8 — one coordinated bump for the slice.

**(b) The L7 captured-turn envelope.** L7 already carries the user message (`TurnLayerSource`); it additionally carries a small typed envelope (`onboarding_input_id`, `artifact_key`, sha, byte count) so the model can *reference* the turn's identity in reasoning without ever being its author.

**Fallback:** if (a) proves too hot for this slice during implementation, (b) alone is the minimum acceptable landing — the card still must not carry turn identity. The implementer surfaces that decision rather than silently downgrading; (a) is the spec's intent because its regression surface (the sha-verification semantics move engine-side) is the one part of this slice needing its own focused test matrix (§9).

---

## 7. Governed inspection tools (bounded, paginated)

Two Stage-0 tools in-slice — both read-only, workspace/project-scoped fail-closed (B3/B4 guard family), with **bounded response schemas** (page size ≤ 20, cursors; prompt bloat must not migrate from opening context into tool results):

- `inspect_statement_history(project_id, statement_id | route_key, cursor?)` — full rows incl. supersession/correction lineage, quotes resolved via the same evidence-reader port.
- `inspect_readiness_history(project_id, gate?, cursor?)` — the ledger, paginated, override-annotated.

**Deferred:** `inspect_client_claim` — that is a *platform-general* exact-claim/provenance read, not a Stage-0 surface; deciding it here would invite a fourth near-identical claim reader later. Ledgered as a platform decision (goes with the C6 toolbelt owner).

Cursors in card `omissions` entries are the same cursors these tools accept; the card names no tool (the resource manifest owns the surface — the agent's resource map tells it which installed tool resolves an omission kind).

---

## 8. Restriction re-homing by enforcement level (Blocker 3)

The 717 bytes of prose in `stage_snapshot.instruction` (`stage0_trial.py:737–748`) split by what actually enforces each rule:

| Rule | Owner (enforcement level) |
|---|---|
| `start_recon` / `synthesize_icps` must not be callable in this trial | **Trial capability surface**: the tools are *not installed* in the trial's effective tool set. Mechanism: the profile registry resolves one profile per role (`registry.py:536`), so this slice adds a named **surface policy** — a trial-scoped profile variant (e.g. `HEAD_OF_ABM` + `surface="stage0_conversation_trial"`) whose pinned tool list excludes the prohibited tools, resolved at the trial composition root. The middleware's allowed-set enforcement (`runtime.py:96–113`) and the resource manifest then both reflect the filtered surface automatically — the model never sees a capability it lacks |
| trusted ids are injected, never authored | **Runtime/tool execution boundary** (§6a) |
| field-level preconditions (verbatim quote, offsets, per-route required fields) | **Tool input descriptions + validators** (already the F8 discipline) |
| how to classify/route statements; UNMAPPED as the honest escape | **`stage0-interview` skill** — routing procedure only; **no trial-specific content enters the shared skill** |
| "this surface is a manual-conversation-only trial" (framing, not prohibition) | **Trial surface policy** artifact/profile prompt of the trial variant — not the shared skill, not the card |
| registered claim fields | **Card data** (§3) + claim-route validator |

Consequences: one coordinated catalog/profile version bump covers §6a's schema changes, the trial profile variant, and the F8 gate-test rows (old versions untouched, per the immutability discipline).

---

## 9. DSAR: the card copy gets an in-slice erasure path (Blocker 6)

`quoted_text` is a derived copy of interview personal data, and **this slice creates it** — so erasure ships with it (the B2 precedent: new personal-data surfaces land with their purge path, unlike pre-existing deferred gaps).

- **Reverse dependency bindings at persist:** the card artifact's subject bindings enumerate **every statement id whose quote it embeds** (per-source bindings, not just a client-level context binding). "Which card artifacts quote statement X" is a direct query.
- **Erasure path:** statement/input erasure (M10.5 `erase`/`object`/`sweep_expired`) extends to dependent card artifacts: tombstone/purge the card body via the existing B2 purge machinery; the artifact row survives as audit (B2's dangling-ref pattern); replay of a journaled context that referenced a purged card **fails soft with the tombstone reason** — it must not resurrect or re-read the body.
- **Recompile correctness:** the next compile excludes the erased statement by construction (the evidence reader returns `ExcludedEvidence`; the card surfaces `excluded_statement_evidence_missing`), and content-addressing guarantees the new card is a different artifact.
- **In-slice executable test (AC-DSAR):** compile card containing statement X → journal a turn against it → erase X and its evidence → run the DSAR path → assert: old card body unreadable; recompile omits X; cold replay cannot recover the erased body; the omission is surfaced, not silent.

---

## 10. Contract-delta: `AgentConstitution` (frozen C6 — unchanged from v1, verified)

```text
- stage_snapshot_ref:     ArtifactRef      →  removed
- readiness_snapshot_ref: ArtifactRef      →  removed
+ project_card_ref:       ArtifactRef      →  added (required)
  budget_envelope_ref:    ArtifactRef      →  UNCHANGED (spend authority, §2.1)
```

Touch points (grep-verified): `contracts.py:415–417` + validator `:423–437`; `ProjectLayerSource` (`context.py:290–319`) → exactly two L3 candidates (card required + budget required), **drops** its `cards.read("project")` call (the card subsumes the project row); `stage0_trial.py:729–764,830–832` → compiles + persists the card; `account_research_turn_wiring.py:280–306,364–366` → merges its two already-small snapshots into one `application/vnd.clue.account-research-card+json`; `specialist_wiring.py:304–306` → child inherits `project_card_ref` (child budget path untouched); `agent_turn_wiring.py:405–412` → one `project_card` journal role label (**impl verifies** whether role strings are a DB enum and whether `DbAgentReplayReader` matches on them — flips in the same commit); contract fixtures. Clean flip per the standing no-backward-compat ruling; all sites in one commit.

---

## 11. Work breakdown (implement-review loop; sequential where files overlap)

| # | Task | Primary files | Depends on |
|---|---|---|---|
| 1.0 | Evidence fixtures: the 48,207-byte bundle; readiness duplication; linear ledger growth; **current routing behavior** (answer round-trip + trusted-id authorship); identity duplication (recorded, fixed in Slice 2) | `tests/` only | — |
| 1.1 | Extend `clue_projections/stage0.py`: `Stage0ProjectCard` + compiler + `StatementEvidenceReader` port + size policy + shared readiness override/lineage helper + migrate ICP synthesis's quote resolution onto the port | `stage0.py`, `clue_research/stage0/icp_synthesis.py` (port adoption), api root (port impl) | 1.0 |
| 1.2 | Current-turn authority: engine-side binding (§6a) + L7 envelope (§6b) + tool-schema shrink + F8 mapping rows | `stage0_tools.py`, execution-seam wiring, `context.py` (TurnLayerSource) | 1.0 |
| 1.3 | Constitution delta + `ProjectLayerSource` rewrite + all wiring flips + journal role labels + replay/fixture updates | `contracts.py`, `context.py`, three wiring sites, `agent_turn_wiring.py` | 1.1 |
| 1.4 | Restriction re-homing: trial profile variant/surface policy + skill cleanup (routing-only) + **one coordinated catalog/profile bump** covering 1.2 + 1.4 | catalog/profiles, registry, trial composition root | 1.2 |
| 1.5 | Inspection tools (two, bounded/paginated) + DSAR reverse bindings + erasure/no-resurrection tests | toolbelt, privacy/purge wiring | 1.1, 1.3 |
| 1.6 | Acceptance (§12): fixture suite + live Aura replay + extensions | — | 1.2–1.5 |

---

## 12. Acceptance criteria

1. **Bounded card, enforced:** a synthetic project with 200 readiness rows *and* 200 distinct effective statements with maximum-length quotes and maximum-size KB values compiles a card ≤ 24,000 bytes with correct omission entries. (Replaces v1's unenforceable "flat ±1 card".)
2. Opening prompt carries only lineage-current, override-applied readiness per gate; a stale-lineage decision and an overridden decision are both represented correctly (fixture for each).
3. Full statement/readiness history retrievable via the two bounded tools; responses paginate; tool calls journaled.
4. The card contains verbatim `quoted_text` (byte-compared against artifact slices); truncation is marked and recoverable via the inspection tool.
5. No `to_jsonb(row)` output reaches model context (walk the assembled L3 messages; assert card schema).
6. **Turn authority:** the model-facing `record_interview_answer` schema contains no `answer` body and no trusted ids; a governed call with model-supplied offsets lands the statement with the engine-loaded bytes; a forged/foreign id attempt is refused at the seam (test).
7. **Capability surface:** the trial profile's resolved tool set excludes `start_recon`/`synthesize_icps`; the resource manifest matches; the middleware allowed-set check passes; a profile advertising an omission-resolving tool it doesn't install is a failing contract test.
8. Determinism: same pinned state + same policy version ⇒ byte-identical card ⇒ identical receipt hashes across two assemblies **and across a process restart**.
9. Crash replay reuses the identical card artifact (content-address hit); no duplicate writes.
10. Cross-workspace compile impossible (raises; test).
11. **AC-DSAR (§9):** erase → old card body unreadable, recompile omits, cold replay cannot resurrect, omission surfaced.
12. Live gate: the Aura/neurosurgery acceptance script replayed end-to-end on the new path (statements routed, product gate, grounded ICP, quit/resume) **plus** a 25+-turn extension with no 422 and a breadth extension (many distinct statements) exercising the statement cap + omission path live.

---

## 13. Evidence trail

Byte-level audit and flow trace 2026-08-01 in-session against `platform/clue-trial` @ `805b867`+29 local commits; artifacts under `.artifacts/s0-trial-63553478967758a6-7566b7bd/` (stage `c01cc8f0…` 32,178 B; readiness `82c01bbe…` 15,889 B; duplication byte-verified; recorded call `f304cf4a…` = 51 messages incl. the double identity injection — **nuance from Slice-0 evidence:** the two system messages are *not* byte-identical; `prompt_body` and `generated_resource_map` are each duplicated while the deepagent copy adds the framework preamble, so Slice 2's fix must assign one owner per payload, not "drop the duplicate message"). Doc A Part III verified as the governing contract. Second-review claims verified 2026-08-01: `stage0.py` exists (commit `08c1998`) with `verdict`/`effective_verdict` at `stage0.py:47–48,161`; `MAX_PROJECT_STATEMENTS = 40` in `icp_synthesis.py`; `RecordInterviewAnswerInput` answer/id round-trip at `stage0_tools.py:286`; `Project` has no version field (`clue_spine/spine.py:87`); ICP proposals are trial-local files (`stage0_trial.py:1317`).
