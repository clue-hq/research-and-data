# CRM integration — Phase 2 live check (2026-10-22)

The first end-to-end run of the write foundation (Task 11 of the Phase 2 plan) on the local
nashville stack, driven in the Claude desktop in-app browser with the founder signed in. Findings
L1–L3 and the double-turn were fixed during the run (rulings R-11.1–R-11.6); the rest are listed
for the founder and the final review.

## Setup
- Stack `./scripts/dev_stack_nashville.sh` on `clue_nashville_pm`, migrated in place to
  `f09f9e286be6`. Head of ABM `v77` (crm-writing v1, crm-sales-analysis v2), recipe 37, manual v23.
- Workspaces: Conduit AI (HubSpot developer test account) and Garner Health (Salesforce Developer
  Edition org), both connected through Composio's dev project since Phase 1.
- Cost (Langfuse, by chat): Conduit re-run and extras $4.27, the first run with the broken card
  $1.22, the Salesforce chat $1.05 — about **$6.50**. The Postgres call ledger carries only the
  naming calls for chat turns; the agent's model spend is Langfuse-only.

## What passed
| Step | Result |
|---|---|
| Propose → card (HubSpot, 2 field updates) | Card renders, records named ("Aldercare", "Cargoloop"), value "Tier 1" |
| Allow + "Always allow" | Both set in HubSpot and read back; permission saved; no message bubble for the answer |
| "What did Clue change today?" | `crm_write_log`, 1½ min, both writes plus the unsent first-run proposal |
| Undo of a covered field | Reversals (`reverses_write_id`) sent with **no card** (standing permission), both succeeded, report 3½ min after the ask |
| "Stop setting ICP tier without asking" | `manage_crm_grants` revoked it (stamped by the person), "none left" |
| Create a contact | First try refused by HubSpot (`INVALID_EMAIL`, `.test` domain): card ⚠ 1 failed with HubSpot's message, agent quoted it and did not substitute an address; retry with `@example.com` succeeded, id recorded in `crm_record_link` as created by Clue |
| Card answered in a second tab | The hidden tab showed the asking card on fronting; the first tab locked its card ~30 s later |
| Answering starts no agent turn (R-11.6) | Four answers recorded `agent_reply = none`, zero agent-turn tasks; the sender's one wake turn reported each time (1–3 min after Allow) |
| Salesforce refusal | "about fifty" into a number field reached Salesforce: `JSON_PARSER_ERROR` on the card; agent reported it and refused to invent a repair value |
| Salesforce overwrite + undo | Employees 1800 → 1850 came out as an overwrite row (unticked, "Who set it isn't known"), succeeded; the undo (1850 → 1800) was a normal ticked group because Clue wrote the 1850 |

## Fixed during the run
- **L1 (R-11.1)** The agent linked the card by its kind (`crm_write_permission`), so the chat showed
  "This review request is incomplete". Finalization now refuses a card link whose id is a gate under
  any other type; the manual's gate line spells the link out (`e672ab95c`).
- **L2 (R-11.2)** Card records showed HubSpot ids; the prepare read now fetches the record's name
  (`e93ad4a27`).
- **L3 (R-11.5)** Card showed `tier_1`; it now shows the option label "Tier 1" (`17c3e5ff3`).
- **Double turn (R-11.3, R-11.6)** Allow started a needless agent turn (9½ min, timed out) ahead of
  the sender's results turn. A card answer can now need no reply: `agent_turn_submission.agent_reply`
  (migration `f09f9e286be6`), the dispatcher and busy checks skip it, the route tells the browser,
  the results message names who allowed what, a decline reaches the agent as a context line on its
  next turn (`0e68df0a1`, `6935eb0d2`).
- **R-11.4** Answering any card adds no message bubble; the turn list carries `answered_gate_id`
  (`fac5e0f75`).

## Decided after the run (same day)
- **L6 → R-11.7, fixed `02c01de08`:** a missing record refuses only its own change
  (`crm_record_not_found`, listed in the tool's `refused`); the rest of the batch goes on the card;
  a batch with every record missing makes no proposal. Residual: a replayed call rebuilt from the
  stored proposal has no `refused` list (needs a column); membership reads are not covered; the
  HubSpot 404 shape is assumed from the executor's handling, a live re-run would confirm it.
- **L8 fixed `5d37c57cd`:** the card, wake message and log show the CRM's message text; the raw
  answer is kept in `crm_write.crm_response` (migration `01b066d230e7`).
- **L9 fixed `8130d6ed2`:** a create's new id is stamped on its log row and named in the results
  message ("Created <label> (<id>)").
- **L5 → R-11.8:** list lookup and creation wait for Phase 3.
- **L10 → R-11.9:** Salesforce field coverage stays at Composio's named arguments; design A (any
  field by API name, checked against the org's definitions, sent through the composite patch)
  noted for later.

## Open — founder questions (as raised during the run)
- **L5 List membership cannot be used.** `HUBSPOT_UPDATE_LIST_MEMBERSHIPS` needs a list id, and no
  connected action lists the lists or creates one (a generic object read of `lists` gets "Unable to
  infer object type"). Clue's own target-account list (the first-release write) needs a create-list
  action or a list the person names. Not exercised.
- **L6 A missing record refuses the whole batch.** HubSpot's 404 on the prepare read refused the
  whole `propose_crm_changes` call (`crm_read_failed`), so the other changes could not ride the card.
  A per-change `crm_record_not_found` refusal would let the rest through.
- **L10 Salesforce `Rating` is not writable** through `SALESFORCE_UPDATE_ACCOUNT` (Composio's schema
  has no `rating` argument), so the picklist pre-check could not be exercised. The allowlisted
  composite patch is the generic route; the agent did not reach for it. Decide whether updates
  should go through the composite patch when the named action lacks the field.

## Open — fixes for the final review
- **L8** The done card prints the CRM's whole JSON error body. Show the message text (HubSpot
  `message` + `errors[].message`; Salesforce `[{message, errorCode}]`), keep the raw body in the log.
- **L9** A create's new record id is in `crm_record_link` but not in the write log, so the agent
  cannot tell the person the contact's id (it noticed this itself).

## Minor
- **L7** Another tab's asking card follows an answer in ~30 s (no turn frame exists now; the safety
  re-read carries it), not instantly.
- **L11** A done card for an overwrite-only batch shows "1 done" with no line naming the change.
- `covered_by` is stamped on writes that were shown on the card when "Always allow" is ticked on
  that same card; harmless, but the column reads as "sent under a grant".
- Underscores in field names render as italics in chat (F7, deferred R-10.10).
- **L4** Turns are slow: 2–7½ min of thinking before a one-line reply, 21 action searches for three
  writes, one 9½-min turn that timed out (the F5/F10 pattern). Out of this branch.

## Not exercised
"Don't allow" on a real card and the decline context line; a new proposal replacing an unanswered
card; a paused batch (connection expired mid-send); the 422/409 answer refusals; list membership
add/remove (L5); the Salesforce picklist pre-check (L10); HubSpot's not-found on the card (L6).
