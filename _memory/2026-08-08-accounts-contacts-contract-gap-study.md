# 2026-08-08 — Accounts & contacts contract-gap study (four-agent read-only sweep)

## What happened

Executed the branch charter's mandatory contract-gap review for integration slice 1
(accounts & contacts flow): four parallel read-only study agents (HTTP inventory;
account-field mapping; contact/committee mapping; runs/launch/chat) over the backend at
`421a9f53`-ancestry vs the frontend Zod schemas. Consolidated deliverable:
**`docs/specs/FI-accounts-contacts-contract-gap-review.md`** — that doc is authoritative
for the findings; this note is the pointer + the operative headlines. No code changed.
Founder has NOT yet ratified anything; the doc's §8 decision register (D-1…D-10) is the
sign-off queue.

## Headlines a future session must not re-derive

- **No account list, contact list, or lookup-by-domain exists anywhere** (HTTP, repo layer,
  or toolbelt). Every backend read is single-entity by uuid, project-run + product scoped
  (`research_view_api.py` scope resolver), while the frontend screens are workspace-global.
- **~51 routes registered, ~29 served by default**: all C7 flags default off (+canary
  allowlist), no CORS middleware in the repo, tenancy = trusted `X-Workspace-Id` header,
  no error envelope. One production app: `clue_api.projections_main:app`.
- **No HTTP path can start research**: launch tools live only on the fleet worker process,
  `entity_research_runtime_enabled` defaults off, and **no production ToolContext ever sets
  `action_ref`** → every human-receipt-gated tool (incl. directive confirmation) is
  currently uninvocable in production. Launch is batch + confirmed-directive + human
  tier-checkpoint + budget-approved; per-account REST kickoff conflicts with authority
  doctrine (decision D-9: HTTP confirmation ritual vs through-Head-of-ABM chat).
- **`researchStatus` cannot be honestly 4-valued**: only `completed`/`needs_review`/
  `cancelled` outcomes are ever produced; `failed` is unreachable (crash → requeued +
  admission-paused + fleet SUSPENDED); "not launchable" (no tier disposition) has no
  frontend state. Legacy `account_run` never advances on the M8D path, so
  `…/accounts/{id}/progress` misleads.
- **Evidence URLs are architecturally excluded** from C7 payloads (`OpaqueReferenceToken`
  rejects `://`; no redemption route exists) — clickable sources are a doctrine decision
  (G4), colliding with the `[B2×presign/frontend]` backlog item.
- **Governance will crash current frontend schemas**: fail-closed display gates serve
  `value_json=null` + RESTRICTED for weakly-bound contacts; frontend Zod `.min(1)`/`.url()`
  floors throw. Redaction vocabulary (D-4) is a prerequisite for flipping any HTTP adapter.
- Pure NO-DATA fields: logo, locationCount, referral/directAccess/recall fit dials,
  avatarUrl, non-LinkedIn socials, influence, account summaryParagraphs, contact
  overviewParagraphs, researchIsRefreshing. `Medium` fit tier is unreachable in live rubric
  config (emits only high/low).
- Right substrate primitives for the D-1 read layer: `claimstore/merge.py::current_values`
  (batch list reads), `ContactEligibilityResolver.resolve_account` (governed committee
  list — NOT `contact_ids_for_account`, which is ungoverned), M8D job aggregation for
  status.
- Chat: no production conversational endpoint, no streaming, append-only content-addressed
  turns → no stable mutable part ids; `review`/`approval` statuses unmapped. Chat = phase-2.

## Latent backend defects surfaced (schedule regardless of integration; doc §7b)

- **L1 (worst):** first `account.value_narrative` claim written will 404 the entire account
  research view (`VALUE_NARRATIVE` routed but absent from `ACCOUNT_SECTION_ORDER`;
  `narrative/research_views.py:241`); no test covers `section_not_allowed_for_subject`.
- L2: no index on `entity_research_job.subject_entity_id`. L3: fleet projection SQL omits
  `unresolved_field_keys`/`committee_status`. L4: `suspend_failure` writes no job-event row.
  L6: `agent_turns_for_project` unbounded. L7: frontend contract prose wrongly claims
  avatars are backend-supplied.

## Next session entry point

Walk the founder through `docs/specs/FI-accounts-contacts-contract-gap-review.md` §8
(D-1…D-10) and get ratifications; then record resolutions into
`apps/frontend/docs/api-contracts/accounts.md` and spec slice 1 (read-only list/detail
through the D-1 read layer). Do not implement ahead of sign-off (charter: no silent
contract decisions).
