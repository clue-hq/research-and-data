# 2026-08-12 — FI-2 Slice 10 Sumble email contract probe

## Scope and result

- Investigation only. Slice 10 production/backend/frontend implementation has not started.
- Created an ignored disposable probe at `.context/sumble-email-probe/probe_sumble_email.py`.
  It writes one credential-redacted JSON artifact per attempted method plus a manifest and keeps
  all output under the ignored `.context/` tree.
- Live OpenAPI discovery confirmed `POST /v9/people` is the current provider-neutral REST route for
  one-person email acquisition. Use list/match mode with a `person_id` or LinkedIn URL and select
  `email` explicitly; a successful terminal result exposes it at `people[].attributes.email`.
- The operation is asynchronous. The kickoff returns `request_id`, `status=pending`, and
  `credits_used=0`; the same endpoint is polled with only the request id. The provider contract says
  the first `succeeded` poll is the 10-credit reveal point.
- One bounded kickoff using Sumble's own public documentation example was accepted and reported
  zero credits used. It was deliberately not polled, so this probe spent no credits and did not
  acquire an email.
- The REST API key is not an MCP credential. MCP initialization returned the provider's typed 401
  explaining that the MCP surface requires its OAuth token flow.

## Recorded evidence and verification

- Final run: `.context/sumble-email-probe/artifacts/20260812T162702Z/`.
- Recorded JSON covers the v9 and v3 OpenAPI GETs, MCP resource-metadata GET, MCP initialization
  POST, v9 email-match kickoff POST, and the aggregate manifest.
- All recorded JSON parsed successfully; request authorization values are redacted; the probe
  compiles; `.context/` remains ignored and the disposable script is not tracked.

## Implementation handoff

- Prefer REST v9 for Slice 10. MCP is a separate transport/auth choice and is unnecessary for the
  ratified Exa plus Sumble acquisition flow.
- Model kickoff/poll durably, make the returned request id replay-safe, settle provider units only
  from the terminal response, and distinguish unmatched person from matched person with null email.
- Do not run the recorded poll until the founder authorizes the reveal cost and the subscription or
  provider contract is ready. Re-check the live OpenAPI pin during implementation because the
  public contract has drifted since the earlier R10 decision note (a v3 surface is now published).
