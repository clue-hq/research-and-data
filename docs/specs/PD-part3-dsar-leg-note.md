# PD-Part-III — DSAR note for design-leg rows and checkpoint threads

**Status:** ratified design note, written by P3.7 (2026-08-14) as the Part-III half the
PD-D8 assessment reserved: *"step 1 lands with Part III (it needs Part III's context-flow
decisions)"* — `PD-D8-dsar-assessment.md` §6. This note records where personal data can now
live in the Part-III surfaces, how each maps onto the D8 erasure-primitive classes, and the
subject-resolvability rulings the delegation bundle settles. **No erasure code ships here**
(same stance as D8 §7): the dedicated post-Part-III compliance slice owns the primitives;
until it lands, the honest DSAR answer for design data — leg rows included — remains
**workspace-level erasure**.

## 1. Where personal data can live in the Part-III surfaces

| Surface | What it can hold | Erasure-primitive class (D8 §5/§6-2) |
|---|---|---|
| `design_leg.bundle_artifact_ref` → the §2.3 bundle artifact | The free-text `brief` (client/operator-authored, may carry personal context); `claim_refs` — **ids + governance stamps only, never values** (the refs-only rule is load-bearing here); content refs; pins (non-personal) | Blob-layer delete/redact of the bundle artifact; the leg row itself carries no personal text |
| `design_leg_exit_journal` | `summary_refs` (free-text summary artifact key + ids); `pending_user_message_ref` — a **reference to the user's original captured artifact**, never a second copy | Redact-in-place on `summary_refs` values + blob-layer handling of the summary artifact; the pending ref dies with the referenced artifact's own erasure |
| `design_agent_run.payload` (the frozen `DesignTurnEnvelope`) | Since P3.4/P3.7 the payload carries `config.delegation_bundle` **by value**, `config.history` (**verbatim user/assistant leg text**), and `config.request.prompt` (the rendered blocks). This is the same personal-text-carrier class D8 §4 flagged for account cards in web-turn payloads — now on every leg turn | The D8 step-2 payload redact-in-place primitive, with `config.history` / `config.delegation_bundle` / `config.request.prompt` named in its closure |
| LangGraph checkpoints (`checkpoint_thread_id` = design run id) | Graph state embedding the frozen envelope (D8 §4.3's gap) | **Now enumerable**: `design_leg` → `design_agent_run.leg_id` → run ids is the join the existing checkpoint deleter needs; extending it is a step-2 item, no longer blocked on discoverability |
| `agent_turn_event_stream` leg frames (delta 8) | `leg_id` + close `reason` only — **no personal text by construction** | No new primitive needed; frames are already pruned by the terminal-turn retention path |
| `agent_thread_message` rows of design turns | The user's leg messages and the turn/leg summaries | Already inside the agent-plane erasure domain (lane-D); nothing design-specific |

## 2. Subject-resolvability rulings (the D8 §6 step-1 questions, answered)

1. **Claim refs are the subject keys entering design — and they stay refs.** The §2.3
   bundle carries claim **ids and governance stamps, never claim values**. Consequence: a
   data subject's claim erasure (M10.5) erases the value at its one home in the claim
   store; the bundle's residue is a pseudonymous id whose subject linkage **dies with the
   claim row**. A DSAR sweep that wants belt-and-braces hygiene can enumerate bundles via
   `design_leg.bundle_artifact_ref` (canonical JSON, queryable), but no personal value
   survives in them by construction. This is the payoff of the refs-only size policy.
2. **The brief and the leg history are client/operator-authored workspace data.** Ruled
   the same way D8 §6-1(b) recommends for binding sets: erasable via **workspace-level
   erasure**, not per-subject DSAR — a client's own campaign prose about their own market
   is controller-side working material. If a brief quotes personal claim values verbatim,
   that is a *usage-policy* problem at delegation time (the head-of-abm holds only
   governed ids via `get_research_view`), not a new storage class.
3. **No new cross-tenant surface.** Every Part-III row (`design_leg`, journal, run
   linkage, stream frames) is workspace-keyed and fail-closed (P3.1's tenancy tests);
   bundle artifacts live under the workspace's artifact scope. The B2 presign caveat is
   unchanged and un-worsened.

## 3. What the post-Part-III compliance slice must pick up (delta to D8 §6)

- Extend the **checkpoint deleter** with the design enumeration (§1 row 4) — the D8 §4.3
  gap is now a mechanical join, not a design question.
- Name `config.history` / `config.delegation_bundle` / `config.request.prompt` in the
  **run-payload redaction closure** (§1 row 3) alongside the account card D8 already
  names.
- Include `design_leg_exit_journal.summary_refs` + the summary/bundle artifacts in the
  design-side **redact/blob primitives** (§1 rows 1–2).
- The exit-judgment eval fixtures (`clue_design/evals/fixtures/`) are synthetic authored
  test data — no DSAR surface.

Revisit triggers inherited from D8 unchanged; add one: **before Part IV mounts the editor
against real-tenant legs**, the workspace-level erasure path must actually name the
Part-III tables (D8's own observation that it "names zero design tables today" now covers
five more).
