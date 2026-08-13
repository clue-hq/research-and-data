# PD — Part III: Agent integration (the design leg on the platform substrate)

**Status: RATIFIED (founder, 2026-08-14) — implementation contract for Part III of
`design-integration-master-plan.md` §3.**
Supersedes the master plan's *mechanism* sketch (the in-graph LangGraph `interrupt` HITL node)
while preserving its *behavioral contract* (§2.1–§2.5) in full. The master plan's §2 diagram
remains the semantic model; this document is how it is built. Grounded in the three Part-III
surveys of 2026-08-14 (platform runtime/turn-ingestion, design runtime/fleet, C8 context
assembly — decision trail in `_memory/2026-08-14-part3-rulings.md`).

---

## 1. The five ratified rulings

### D1 — HITL is durable leg state, not a LangGraph `interrupt`

The design leg is a **durable `design_leg` row**, not a suspended graph. The master plan's
four-node graph materializes into the substrate:

| §2 graph element | Materialized as |
|---|---|
| HITL node (`interrupt`) | The ingestion **routing rule** + leg state `open_awaiting_user` |
| Design-deepagent node | A design turn executing on the leg (design fleet lane) |
| END | `finish_design_leg` → leg state `closed(reason)` |
| "Attach as subagent" wrapper | The delegation entry that opens the leg |

Why: the repo uses `interrupt()` zero times and carries standing rulings against it
(M13.1's finalize→resume precedent in `platform/api/clue_api/review/handler.py:1-12`;
lane-D charter "No LangGraph `interrupt()` anywhere"), chosen to keep the Temporal swap
mechanical. And an interrupt is only as good as what the checkpoint captures: the design
runtime's working state (scene under construction, rounds, `final.json`) lives outside the
LangGraph checkpoint (`lumen_agent/checkpoint.py:1-40` — resume-as-restart, honestly
documented), so a "suspended" graph resumed elsewhere would wake with messages intact and
its design substrate gone. With turn-terminal legs, a *waiting* leg's full state is
document + leg history + leg row — all already durable — so §2.5's durable-interruption
property and the kill-worker/resume gate test hold on today's substrate. A mid-**turn**
kill remains fence-protected restart of that turn (same as every platform lane; seconds of
redone work, never lost conversation). A waiting leg holds zero worker resources.

**The routing rule (replaces "innermost interrupted graph"):**

> When a user message arrives on a thread: if the thread has an **open `design_leg`**, the
> message becomes a design turn on that leg, delivered straight to the design deepagent.
> Otherwise head-of-abm receives it. No other routing input exists.

This is a single indexed row lookup in the ingestion path — deterministic, no LLM in the
loop, no per-message misrouting risk. While a leg is open the design agent owns the thread.

### D2 — One platform-facing role; the trio stays internal

We register the **entire composite design deepagent** as one platform role:
`AgentRole.DESIGN`. Internally the existing structure is unchanged: the orchestrator
remains the main design agent with its two deepagents-native subagents (DSL author, visual
reviewer), separate prompts/skills/models/tools per role, coordinating through the design
runtime's shared virtual workspace and typed state, all running as one design
job/execution. There is no `AgentRole.DESIGN_AUTHOR` or `DESIGN_REVIEWER`; the trio is not
three governed executions and not three services. From the platform's perspective it
delegated to "Design": one governed role, one leg, one summarized outcome — a *doorway,
not a container*. This is the faithful port the master plan §3-III-1 describes
("unchanged in its internals"); splitting the trio into isolated governed executions would
be a rewrite of its operating model, not a port.

### D3 — Execution lane and streams

Design-leg turns **execute on the existing `design_job` fleet lane** (synchronous body,
Rust/node subprocesses, 4 Hz design stream — all preserved) and **also land as
`agent_turn` rows** on the shared thread (role=`design`, scoped under the platform parent
via `parent_execution_id`) so §2.5's one-thread/attribution contract holds. Leg lifecycle
events (opened / awaiting user / closing / closed) ride the chat turn stream; `design.*`
build progress stays on its existing token-authenticated `design_run` subject stream.
Rendering both as one visual stream is **Part IV's** concern, stated here so it is not
rediscovered as a Part III gap.

### D4 — Concurrency

Lane-D's ratified per-thread single-flight stands ("one active turn per thread").
Concurrent design sessions per user are **across threads** — each design session lives on
its own thread. This resolves the open leaning in `PD-part2-design-substrate.md` §353-357:
the fleet DOES host the design deepagent (it already does, post-D5); restart-survival is
D1's property; multi-session concurrency is thread-parallelism.

### D5 — Delegation-bundle gaps

- **Content-schema instance**: no content plane exists platform-side. The bundle carries
  design's real vocabulary instead — nullable `binding_set_ref` / `template_revision_ref`
  plus free-text `brief`. No new platform content type is fabricated; the Doc S decision
  stays open and un-forked.
- **Target document pin**: `design_document` has no immutable version rows, so the pin is
  `(workspace_id, document_id)` + `current_version` as a **CAS guard** (optimistic,
  mismatch = honest refusal), not a frozen snapshot.
- **Brand kit pin is fail-closed**: the bundle pins `(brand_kit_id, version)` against
  `design_brand_kit`'s PK (built for exactly this — migration `51db518c2a68:109`). When a
  bundle pin is present, the design entrypoint's silent platform-default fallback
  (`lumen_api/main.py:8154-8158`) is an **error**, not a fallback. Unpinned turns
  (standalone editor) keep today's behavior.

---

## 2. The leg contract

### 2.1 `design_leg` (new table)

One row per leg. Columns (shape, not DDL): `id`, `workspace_id`, `thread_id`,
`parent_execution_id` (FK → `execution`, the delegating platform execution),
`opened_by_turn_id`, `state`, `bundle_artifact_ref` (the C8 bundle, content-addressed),
`document_id` + `document_version_guard` (nullable — a leg may create the document),
`brand_kit_id` + `brand_kit_version` (nullable pin), `close_reason`
(`locked | out_of_scope | abandoned`, null while open), `closed_by_run_id`, timestamps.
State machine:

```
open_awaiting_user ──(user msg → design turn dispatched)──► running
running ──(turn ends, leg still open)──► open_awaiting_user
running ──(finish_design_leg validated)──► closed(reason)
closed ──(re-delegation names this leg id)──► open_awaiting_user   # mis-exit reopen
```

At most one **open** leg per thread (partial unique index) — the routing rule's lookup key
and D4's invariant. Exit decisions are journaled append-only (leg id, reason, summary refs,
pending_user_message ref, deciding run id) — reopening never erases the record.

### 2.2 `finish_design_leg` (engine-validated exit; master plan §2.2 verbatim)

`finish_design_leg(reason = locked | out_of_scope | abandoned, summary_refs, pending_user_message?)`
— exposed to the design orchestrator only; the engine validates shape, requires
`pending_user_message` when `reason=out_of_scope`, journals, flips the leg, and on
out-of-scope **re-submits the pending message as a fresh head-of-abm submission** on the
same thread (the user never repeats themselves). Reconciliation with the design harness's
existing authorities: `final.json` / `finalize_run` / `request_clarification` remain the
**turn-level** outcome contract, untouched; `finish_design_leg` is the **leg-level** exit
and is the only path to `closed`. A turn can finalize (proposal ready) while the leg stays
open — that is the normal iteration loop.

### 2.3 The delegation bundle (C8-native)

One canonical-JSON artifact + version-pinned `domain_ref`, attached as
`ProjectContextArtifact(name="design-delegation-bundle", …)` on the design role's
constitution — byte-for-byte the shipped `research-directive` pattern
(`account_research_turn_wiring.py:380-403`); zero assembler-core changes. Schema v1:
`workspace_id`, brand pin (D5), target document pin (D5), `claim_refs[]` (ids + governance
stamps, `ContactHandoffClaimRef` vocabulary), `binding_set_ref?`, `template_revision_ref?`,
`brief`, turn-contract flags (propose→Accept/Reject; one-clarification-round). **Hard size
policy on day one** (refs-only; own byte cap enforced at build) — it lands `required=True`
in the 48k L3 layer the C8 card can half-fill; an oversized bundle must fail the build
loudly, not the turn confusingly. Carried into the design worker on
`DesignTurnEnvelope.config` (already the frozen by-value bundle carrier). Memory (Doc M)
is **not** in the bundle — L4 already assembles brand-scoped preferences for any child
constitution inheriting `brand_id`; duplicating advisory preferences into a required
artifact would mix the species Doc M forbids.

### 2.4 Leg-scoped history (§2.5's filtered assembly)

New: a leg-aware history store variant at the `ConversationTurnEngine` seam
(`conversation_turns.py:199-202`). Design turns assemble: bundle + full leg history (all
user↔design exchanges + document/round outcome refs). Head-of-abm assembles: own-role
turns + leg **summaries** (the `DelegationResult`/`AgentFinalizeEnvelope` body-free
shapes, reused). Neither ingests the other's transcript. The design runtime has **no**
cross-turn history today (fresh agent + scene re-POST per turn) — this store is net-new
work under either HITL mechanism and is the real "consistent context window". P3.2's
cache-stability preservation is what makes the reassembled prefix economically one
continuous session (~95% cached prefill).

---

## 3. Frozen-contract deltas (enumerated once)

1. **`AgentRole.DESIGN`** (`contracts.py:210`) + one coordinated migration widening the
   three role CHECKs (`agent_turn_role` @ `7e9269ed8a81`, `agent_plan_role` +
   `agent_delegation_roles` @ `6628a407e993`) + `SpecialistTaskEnvelope.role` Literal +
   `_REQUIRED_ACTIVE_ROLES` + required-output-path table + `C6_ACTIVE_PROFILE_VERSIONS`
   entry. One commit, per the C8 §8 precedent.
2. **`design_leg`** table + exit journal (§2.1) + partial unique open-leg index.
3. **`design_agent_run` linkage**: nullable `leg_id`, `execution_id` (new runs stamped;
   legacy rows stay NULL — same pattern as B3's workspace stamping).
4. **`focus_refs` widening** (three narrowings move together): `ContextRefRequest.object_type`
   Literal, the `agent_turn_submission_context_ref` DB CHECK (`39513bbba38a:44`), and a
   `design_document` branch in `DbCompiledContextCardReader.read` — else design refs are
   silently dropped at `context.py:425-426`. Canvas selection (`target_node_ids`,
   `active_page_id`) rides `focus_refs` per master plan §2.4.
5. **`previous_turn_outcome`** gains its platform field on the submit contract, threaded to
   design turns (today it exists design-side only, with zero production senders).
6. **Gateway** (P3.2): `GatewayConfig` passthrough for OpenRouter `extra_body`
   (`provider.sort` replica pinning + `usage.include`); a `supports_image_input`
   capability seam on `AgentModelProvider` (replaces the raw-key preflight probe);
   per-role `ModelPolicy`; **exactly one durable per-role usage record** (role promoted
   into the gateway's durable ledger; the design-local capture retires — no double count).
7. **Tool authority**: the 47 `design_*` grants flip from `()` (reason
   `design_agent_not_wired_until_part_iii` retires) to the design role, plus
   `finish_design_leg` — a deliberately noisy authority-audit change Part II staged.
8. **Turn-stream vocabulary**: leg lifecycle event types added to the chat turn stream;
   `run_event.subject_kind` untouched in Part III.

## 4. Slices

| Slice | Content | Gate |
|---|---|---|
| **P3.1 Schema & vocabulary** | Deltas 1–5 | migrations up/down/up green; role visible end-to-end; a design focus_ref survives submission→L5 |
| **P3.2 Gateway move** (independent; start immediately) | Delta 6; live probe of image-blocks-through-Responses-API + reviewer `ToolStrategy`; design harness builds its three role models via `AgentModelProvider.build` | a real design turn on the platform gateway: images flow, attribution once per role, cached-prefill ratio preserved |
| **P3.3 Catalog registration** | Design profile/prompt/skills as catalog entries; delta 7 | authority audit green with the new grants; profile resolution end-to-end |
| **P3.4 Leg engine** | `design_leg` runtime + delegation entry on head-of-abm + bundle assembly (§2.3) + the routing rule at ingestion/worker + leg-scoped history (§2.4) + `agent_turn` rows for design turns + speaker-state projection | full loop: strategy turn → delegation opens leg → N direct design turns with canvas focus_refs → head-of-abm untouched throughout |
| **P3.5 `finish_design_leg`** | §2.2: validation, journal, out-of-scope re-delivery, mis-exit reopen | lock-in returns summary + head-of-abm resumes; out-of-scope answers without repetition; reopen restores context |
| **P3.6 Evals & resilience** | Exit-judgment golden set in the regression harness; kill-worker/resume leg test; single-flight + cross-thread concurrency tests | master plan §3-III gate paragraph, verbatim |
| **P3.7 Close-out** | Stream bridging per D3; DSAR note for leg rows/checkpoint threads (PD-D8 assessment said Part III designs this); docs/memory | Part III gate demo, recorded |

Sequencing: P3.1 ∥ P3.2 → P3.3 → P3.4 → P3.5 → P3.6/P3.7. P3.2 first among equals — it
retires the largest cost/risk unknowns (Responses-API image translation, prefill economics)
before anything depends on them.

## 5. Known residuals accepted by this contract

- Mid-turn worker death = fence-protected restart of that turn (not resume). Named,
  accepted, same class as every lane; the B1 hard-fence follow-up still owns the zombie
  window.
- Design tool-substrate reconstructibility (`checkpoint.py:36-39`) is **not** required by
  Part III anymore (D1) — it remains the seam for a future true mid-turn resume.
- One-stream rendering, the speaker chip UI, and `previous_turn_outcome`'s frontend sender
  are Part IV surface work; Part III delivers the data they read.
- Cooperative-only cancellation of design turn threads (fleet_handler) — inherited,
  documented, unchanged.
- `agent_model_call.cost_millicredits` hard-coded 0 — P3.2 records real cost per role or
  explicitly re-defers with a note, but must not double count.
