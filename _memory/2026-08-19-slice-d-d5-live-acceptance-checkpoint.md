# 2026-08-19 — Slice D / D5 live acceptance checkpoint

> **Superseded blocker ruling, later 2026-08-19:** the founder removed signal-tier eligibility for
> explicit Account research. `high`, `low`, absent, and signal/effort vocabulary mismatch must not
> block an exact user-selected Account. The implementation and continuation state are recorded in
> `2026-08-19-explicit-account-research-not-tier-gated.md`. The evidence below remains the accurate
> pre-fix diagnosis; its request for a per-account tier override is no longer the chosen remedy.

**Branch:** `platform/comprehensive-account-contact-research-v2`.
**D5 code/test commit:** `e3756c45`.
**Full-suite baseline ledger:** `b4f62be3`.

## Preserved runtime (do not replace while acceptance is open)

- PostgreSQL: `clue_d5_live` on the existing local instance.
- Storage: `/private/tmp/clue-d5-live-20260819/artifacts`.
- Agent workspaces: `/private/tmp/clue-d5-live-20260819/agent-workspace`.
- Frontend: `http://localhost:3010` (existing Next process).
- Projections/API: `127.0.0.1:8006` (existing process).
- Fleet: existing Tunis fleet process started 2026-08-19 02:16 IST.
- Workspace: `ws_da1d3068e39d4d749b807e4ee4e1a0e2`.
- Project: `prj_0dc5d508c0eb50dbac620b1263bcc8ad`.
- Thread: `thr_d088773c288156699798e3cddcea0dbe`.
- Project run: `1e7f98b7-9c5a-5b85-86f1-45c8d35df9fe`.
- Selected Account: Christie Clinic, `8720cb06-2ba9-4224-9020-c1aedb80a078`.
- Client website correction remains `https://insighthealth.ai/` (not `insight.health`).

## What the live browser journey proved

- The signed-in user durably approved the product-selection and ICP-confirmation gates.
- A real Exa Websets discovery request was created and polled to completion. Discovery committed
  ten project accounts, scoring committed ten rows, and the project run spent `62.860` cents before
  pausing at `tier_checkpoint`.
- The user's first Account command was captured on turn
  `031bc57c-c62a-5d97-9d10-6bc0809747d0`: research Christie Clinic in depth and resolve its buying
  committee. The agent drafted directive `2bd0eb16-7e16-50dc-b05d-bbeabb97fb0b` and correctly
  refused launch because the Account had no exact human-selected tier claim.
- The next user turn, `43963325-033c-5e76-b1c3-da0bb32afc63`, explicitly says to present the tier
  checkpoint, approve the proposed tiers, and select Christie Clinic at high tier. The agent
  durably recorded that text through `record_interview_answer@1`, then correctly reported that it
  cannot execute the human-only checkpoint action.
- No `entity_research_run` exists yet and no Sumble committee call was made. The refusal occurred
  before account-research provider spend.

## Exact blocking contract mismatch

The live checkpoint is numeric scoring mode. All ten accounts provisionally scored `low`; Christie
Clinic has fit `1.0`, intent `0.0`, the same score as multiple peers. The numeric checkpoint supports
only `action`, global `cutoffs`, and budget cap. Although `CheckpointDecision` parses
`approved_account_ids`, that field is consumed only by discovery-criteria mode; numeric scoring
ignores it.

Therefore the recorded human instruction cannot be represented faithfully today:

- approve unchanged cutoffs -> Christie remains `low`;
- loosen global cutoffs -> several accounts become `high`, widening the human decision;
- write a one-off high-tier claim -> forges authority outside the checkpoint result.

There is also no HTTP/frontend route for `submit_tier_checkpoint`; the generic tool is steering and
correctly excluded from model authority. The browser conversation can record intent but cannot
apply this checkpoint. A founder ruling is required before changing semantics: either add an
audited per-account tier override to numeric scoring, or approve a broader cutoff-based high-tier
set. Do not silently choose either.

The launch precondition exposes a second vocabulary mismatch: the drafted directive's effective
effort tier is `standard`, while this ICP checkpoint emits `high` / `low`, and
`compute_account_research_estimate` requires exact equality between the human tier claim and the
directive effort tier. Therefore an otherwise-valid `high` or `low` checkpoint claim would still
not admit this draft. The correction must freeze how selection tiers map to account-research effort
tiers (or make them one vocabulary); do not bypass the equality check in live data.

## Browser-control status in the resumed ChatGPT session

The original Chrome window, authenticated request traffic, and server processes remain alive.
The resumed session could not inspect Chrome: both bundled browser control and Computer Use fail
before any UI action because the Node automation runtime lacks the required privileged capability
(`createElicitation`; the initial package import also lacks the `process` global). Opening the
ChatGPT app did not change that per-session tool capability. No browser state was navigated,
reloaded, or replaced during these attempts.

## Safe continuation

1. Obtain the founder ruling for numeric-mode per-account tier override versus broader global
   cutoff approval.
2. Apply the human decision through a non-model, audited action carrying user
   `usr_30591303cec447748625a4e0216219b1`, membership
   `wsm_12c2cf8570584f2d9d8a5ba0ce55dbf4`, and action ref
   `turn-action:43963325-033c-5e76-b1c3-da0bb32afc63`.
3. Reuse the existing draft directive and exact Account context; the direct-launch tool can confirm
   the draft and launch once the exact tier claim exists.
4. Continue the real Sumble/account-agent journey, then verify contacts read, role/persona claims,
   `llm_synthesis` provenance, request organization lineage, run lineage, and visible UI.
