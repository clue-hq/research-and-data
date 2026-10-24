# CRM Phase 3 — live check findings (2026-10-23/24)

Live check of Phase 3 (first writes) on the nashville dev stack, branch `feat/crm-integration-phase-3`
at `2190d64ce` (Head of ABM v78, crm-writing v2, recipe 38, manual v24), stack DB migrated in place to
`31b850b308e6`. Test CRMs: Conduit AI → HubSpot developer test account; Garner Health → Salesforce
Developer Edition. Driven through the in-app browser (founder asked Claude to drive it).

## What passed

**HubSpot (Conduit AI, project "Conduit AI hotel operators")**

- "Put our top 10 target accounts into HubSpot with their ICP tiers": the agent read
  `read_crm_targets`, `find_crm_list` (none), searched HubSpot by domain (none of the 10 there),
  picked the discovery run's 10 strict-pass accounts (87 of 90 are tier 1; it named the choice) and
  proposed one card: create the list "Clue: Conduit AI hotel operators" + create 10 companies with
  Target account = true and ICP tier = tier_1, each with its `clue_entity_id`. Allowed → 11/11
  succeeded; list 18 stored in `crm_list` for the project (`clue_created`); 10 `crm_record_link`
  rows with their Clue accounts, `created_by_clue`. HubSpot read-back: both fields set.
- The wake turn found the list and the new ids and proposed the 10 list adds; first try refused
  (`record_ids` must hold one record per change), the agent repaired into 10 single adds. Allowed →
  10/10; HubSpot shows them on list 18.
- "Add the buying committee for these accounts as contacts": none of the 10 has been researched —
  the agent wrote nothing, said so, and offered Atrium (the one account with a writable committee).
- "Use Atrium instead": the first proposal was refused (`crm_field_forbidden`: the free-text
  "Company Name" on a person); the repaired card created Atrium (Target account, tier 1) + 5
  contacts (checked email, job title, LinkedIn where identity-bound; Kimberly Furlong's LinkedIn
  withheld by the agent — the URL named someone else). Partial approval: only Atrium + Rob
  Mangiarelli allowed → 2 succeeded, 4 `skipped` "Not chosen", no grants created. HubSpot: Rob has
  name, email, title, LinkedIn, no phone.
- Linking Rob to Atrium after the fact (`HUBSPOT_UPDATE_CONTACTS` `associatedcompanyid`): HubSpot
  applied it (primary company + association) — but see L-3.
- "Remove Montage Hotels & Resorts from the Clue list": one card, allowed, removed; the company
  record stays. HubSpot list 18 now has 9 members.
- `HUBSPOT_SEARCH_CRM_LISTS` returns list 18 by `listIds` and by name, with `processingType`
  MANUAL and its size.

**Salesforce (Garner Health, project "US employer benefits")**

- "Put this project's target accounts and their buying committee into Salesforce, in the project's
  Clue campaign": card 1 created the 2 missing accounts (Syracuse City School District, Carmel Clay
  Schools) before their people (R-6.18); the agent named the 3 people held back for no checked
  email. Card 2 (after a refusal: the agent sent campaign `status` "Planned", R-12.9 requires it
  omitted) created the campaign "Clue: US employer benefits" + 6 contacts linked to their accounts;
  2 unticked (see L-5) → 5 succeeded, 2 not sent. Card 3 added the 4 to the campaign (status Sent).
  Salesforce: campaign active, "In Progress", 4 members, each on the right account. Campaign stored
  in `crm_list` for the project.

## Findings

| # | What | Severity | Proposed |
|---|---|---|---|
| L-1 | **A card cannot use records it creates.** A list add needs the company's id; a contact's company link (HubSpot association / Salesforce `AccountId`) needs the account's id. Both exist only after the create, so "create + add/link" takes two cards. The agent spent many rounds working this out (first turn 7 min 48 s, 21 rounds). On Atrium it put the company and its people on one card, so the people were created unlinked and needed a third card. | Founder decision | (a) extend `new:` to records (e.g. `new:company:<domain>`), filled in by the executor like the list id (R-12.7's one-card intent); or (b) keep two cards and teach the skill: create missing companies first, then people with their company link, then list adds |
| L-2 | **Composio search for write actions is wording-sensitive**: "add companies to a list" and a long combined query returned nothing; "add to list" found it. | Minor | Skill hint with the exact wording, or a curated synonym in `find_crm_actions` |
| L-3 | **False "not applied"**: the `associatedcompanyid` update was marked failed ("The CRM reported success but the value did not change") although HubSpot applied it — the read-back ran 2 s after the send through the search endpoint, which lags. The agent then read the contact and reported the truth. | Important | Read back by record id (batch read), or retry the read-back once after a short wait; root-cause in the fix pass |
| L-4 | **One record per list change is not taught** — one refused try before the agent split the adds. | Minor | One line in crm-writing §3b |
| L-5 | **Names split badly**: `read_crm_targets` splits the full name at the first space, so "Dr. Holly Herrera" → first "Dr.", last "Holly Herrera"; "Bethany Maciel, MBA, SHRM-CP" → last "Maciel, MBA, SHRM-CP". (Both unticked in the check.) | Important | Strip honorifics/credentials before splitting, or use a structured name from the research when present |
| L-6 | **Card labels show raw ids**: "Added 10 companies to the list "18"", "Add 4 contacts to the campaign "701jV00000HsI7qQAF"", "Set Primary Associated Company ID … → 355964361431". | Minor | Show the list/campaign/company name (Clue knows it) |
| L-7 | **Wake message saved as the person's words**: `record_interview_answer` recorded "aryan keshri allowed 11 of 11 changes." as a project statement. | Minor | Prompt/skill: never record a derived (system) message as an interview answer |
| L-8 | **Held-back people not always named**: the committee answer did not mention Dana.AI's 3 people held back for no email (it did on Salesforce). | Minor | Skill wording already asks for it; watch |
| L-9 | **`retry_of` misuse**: the agent set `retry_of` on a proposal refused at prepare; refused with `ExecutionConflict`. | Minor | Tool note: a refused proposal is re-proposed, not retried |
| L-10 | **A turn abandoned after a network drop is never re-run**: the wake turn lost the network (laptop asleep), was abandoned after 16 min; the fleet's later retries failed `ExecutionConflict`. Not CRM-specific. | Platform, note | Out of CRM scope; record for the turn-runtime owner |
| L-11 | **Failed turn display**: a failed turn shows the raw code "a_p_i_error"; after a reload the chat showed "Thinking…" + Stop on a finished turn until it was scrolled. | Minor (frontend) | Add to the open frontend bugs (L12/L14) |

## Re-run after Tasks 10–11 (2026-10-24, Head of ABM v80)

**Passed**

- Garner (Salesforce): "Add Holly Herrera and Bethany Maciel to Salesforce and to the project's Clue
  campaign" → one card: 2 contacts created with cleaned names (Holly / Herrera, Bethany / Maciel —
  R-12.12) on Carmel Clay Schools, plus 2 campaign adds by `new:contact:<email>` (R-12.11) filled
  with the new ids; card title 'Add 2 contacts to the campaign "Clue: US employer benefits"'
  (R-12.13). Salesforce read-back: both members, status Sent. The wake turn made no
  `record_interview_answer` call.
- Conduit (HubSpot): ATMA Hotel Group and Baywood Hotels created with tier and Target account, and
  both list adds sent with the new company ids (`new:company:<domain>`); card title 'Add 2 companies
  to the list "Clue: Conduit AI hotel operators"'.

**Step 4 (deleted-list recovery): failed** — see L-12.

| # | What | Severity | Proposed |
|---|---|---|---|
| L-12 | **A list deleted in HubSpot is not recognised as gone**: HubSpot answers an add to a deleted list with "Attempted to modify membership for deleted lists: [PortalListId{…listId=18}]", which `_fail_gone_list` does not match (it matches the 404/LIST_NOT_FOUND the spike saw). So `crm_list.gone_at` stays empty; the agent's recreate was refused `crm_list_exists`, and it re-proposed adds to the deleted list. | Important | Recognise this answer as gone; mark the list gone; the recreate then passes |
| L-13 | **A card can be left invisible**: twice the agent finalized `awaiting_input` with a message but without `open_gate_refs`; the card existed (`awaiting_permission`) but no gate part reached the chat. The contract accepts a message alone. Not CRM-specific. | Important | At finalize, add every still-open gate this turn created to `open_gate_refs` |
| L-14 | **L-7's prompt line did not hold**: on the Conduit wake turn the agent again recorded "aryan keshri allowed 4 of 4 changes…" as an interview answer (it did not on Garner). | Founder decision | Code check (R-12.14 option A) instead of / as well as the prompt |
| L-15 | Wake replies list internal write ids ("write_id 0cc0e845-…") | Minor | Skill/tool note: don't quote write ids to the person |
| L-16 | A finished card kept showing "Sending changes…" until reload (likely L12 in the open frontend bugs) | Minor (frontend) | With L12 |

The `retry_of` misuse (L-9) happened again.

## Not exercised yet

- Deleted-list recovery (step 4) passing end to end — after L-12 is fixed.
- Removing a member Clue did not add (unit-tested).

## Cost

TBD (Langfuse) — six Head-of-ABM turns on Conduit, five on Garner.
