# Own OAuth apps — live check findings (2026-10-25)

Live check of Clue's own HubSpot and Salesforce apps (R-14.1–R-14.3) on the nashville dev stack.
The branch had been fast-forwarded to `integration/f3-onto-crm-phase-4` (CRM Phase 4 + F3 agent
workspace), so the stack DB was migrated in place `53f06d57df36 → b1d0eb59cd73` and the check runs
on the merged code. Both old connections (Composio's shared apps) were marked expired in the lane DB
so the chat offers a Reconnect card. Running record — updated as the check goes.

## What passed

**Salesforce (Garner test org `orgfarm-8eff0bfa43`, Shashank's)**
- Reconnect card → Composio → Salesforce consent → connected; the new connection is `active` on
  auth config `ac_k9cNBS3hGCgM` (Clue's packaged external client app), the old one stays `expired`.
- `SALESFORCE_WHO_AM_I` works with the `id` scope (the open question from R-14.2); a SOQL read works.
- Clue's field setup on the new connection: "0 created, 16 already there", permission set found,
  read back, registry `ready`.
- The agent linked the project's existing Clue campaign to the new connection by itself
  (`link_crm_list`).
- Writes through the card: `SALESFORCE_ADD_CONTACT_TO_CAMPAIGN` (second Holly Herrera, status
  "Sent") succeeded and was confirmed by SOQL on `CampaignMember`; `SALESFORCE_REMOVE_FROM_CAMPAIGN`
  then succeeded. The only refused change was the undo (D-2).

**HubSpot (Conduit AI test portal 247744687)**
- Reconnect card → consent for app **58593738** (Clue's own app; the shared app was 11217553) →
  connected `active` on auth config `ac_jD3YXBrp_2ed`; the old connection stays `expired`.
- `HUBSPOT_LIST_GRANTED_SCOPES` returns **exactly the 13 scopes** of R-14.1, nothing more.
- Reads: company search by domain (incl. Clue's own `clue_tier`/`clue_id`), deal search.
- A permission Clue did not ask for is refused cleanly: a ticket read returns HTTP 403 "The scope
  needed for this API call isn't available" with `successful: false` — nothing silently empty.
- Clue's field setup on the new connection: "0 created, 9 already there", the "Possible duplicate"
  label found by name (type id 2), registry `ready`.
- Writes through the card: Atrium added to the Clue list 19 (read back by
  `HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS`), then removed (read back: no lists).
- Replacing the connection closed an unsent Phase 3 card in another Conduit chat (`thr_9a8eef…`)
  and woke that chat, which re-proposed it on the new connection (designed behaviour,
  `close_replaced_connection_proposals`). That card is left waiting for the founder.

**Not exercised:** HubSpot contact field write and HubSpot duplicate link on the new app (the same
`crm.objects.contacts.write` scope as the passed writes); a disconnect-and-reconnect of the *new*
connection.

## Defects and findings

- **D-1 — Two chats of one project waking at once can deadlock (F3 code, Important).** On connect,
  `queue_crm_connected_turns` woke both Garner chats that were waiting on the CRM, 0.5 s apart. Both
  turns ran `ensure_project_library` → `lock_project` (`SELECT … FROM project … FOR UPDATE`) and
  Postgres reported `deadlock detected`; one turn (`932ceb04…`) failed with "Response failed", the
  other (`de3afdb2…`) went through. Code path: `agent_turn_fleet_wiring.py:740` →
  `project_library.py:607` → `arv2/project_documents.py:463`. Lock order between the project row and
  a row the other turn holds is not the same in both turns. Owner: the F3 agent-workspace lane.
  **Fixed (founder asked to fix it here) `2e367467b`:** `lock_project` takes `FOR NO KEY UPDATE`, which still serializes every
  writer that takes it but does not conflict with the key-share lock a foreign-key insert holds
  (the pin's FK to `project`). Taking the lock earlier instead would hang: the artifact store binds
  artifacts to the project on its own connection. Regression test
  `test_two_turns_that_each_reference_the_project_both_get_its_lock`. **Re-checked live:** the same
  scenario (two Garner chats woken by one Salesforce reconnect) — both turns finished, no deadlock.
- **D-2 — A reconnect to the same CRM loses undo of every earlier Clue change (CRM, Important).**
  `_reversed_writes` only accepts writes made on the current `connection_id`. A reconnect (expired
  token, or the move to Clue's own apps) creates a new connection row for the same org/portal, so
  "undo Clue's possible-duplicate link" was refused twice ("This undo does not match a change Clue
  made"). The same per-connection keying applies to Clue's field registry, list links and record
  links: the agent worked around those (setup re-ran, campaign re-linked), but undo has no
  workaround. Suggested fix: treat a new connection to the **same external account** (same Salesforce
  org id / HubSpot portal id) as the same identity for undo, lists, record links and Clue fields; a
  switch to a different org/portal keeps today's behaviour. Needs a ruling.
  **Fixed `dc2627ae2`:** completing a connection asks the CRM who it is (`HUBSPOT_WHO_AM_I`
  `portal_id`, `SALESFORCE_WHO_AM_I` `organization_id`) and stores it in `external_account_id`;
  the same account reuses its connection (status back to active, new grant), another or an
  unidentified account is a new connection. Founder approved the approach 2026-10-25.
  **Re-checked live:** Garner's expired Salesforce connection `34845800…` came back `active` on
  reconnect with the new grant and its org id; no new row.
- **D-5 — A pre-existing test failure on the merged branch (not CRM, not D-1).**
  `tests/api/test_project_context_files_db.py::test_status_facts_are_workspace_scoped_and_keep_person_only_accounts`
  fails with an `arv2_job_run_scope` foreign-key violation while seeding an `arv2_research_job`,
  with or without the D-1 change. Owner: whoever owns that test (ARV2 / F3 merge).
- **D-3 — The first reconnect turn failed before the migration (setup, not a defect).** The branch
  had moved to the merged code while the DB was still on Phase 4's head; every turn failed on
  `project_library_epoch`. Fixed by migrating; noted so a lane that pulls the merge migrates first.
- **D-4 — The agent cannot open the connect pop-up (test harness, not product).** The in-app browser
  blocks pop-ups from agent clicks, so the founder clicks Connect. No product change.
