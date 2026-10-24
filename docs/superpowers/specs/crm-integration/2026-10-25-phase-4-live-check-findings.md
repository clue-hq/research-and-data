# CRM Phase 4 — live check findings (2026-10-24/25)

Live check of Phase 4 (Clue's own fields) on the nashville dev stack, branch
`feat/crm-integration-phase-4`. The first half ran on the Task 6 head; the stack was restarted on
`e885c7cf1` (the final review's fix pass) before the last four checks. Head of ABM v82,
crm-writing v5. Stack DB `clue_nashville_pm` migrated in place to `53f06d57df36`. Test CRMs:
Conduit AI → HubSpot developer test account; Garner Health → Salesforce Developer Edition. Driven
through the in-app browser.

## What passed

**Setting Clue's fields up (owner/admin card)**

- HubSpot: the `clue` property group on companies and contacts, 6 properties (`clue_id` unique on
  both) and the contacts↔contacts label "Possible duplicate" — 9 created, read back, label listed
  by name. Registry `ready`.
- Salesforce: 16 created, including the `Clue_Possible_Duplicate__c` lookup; Clue made its own
  permission set `Clue_Fields` with read+edit and assigned it to the connected user (R-13.1), with no
  step by hand; read back by SOQL before `ready`.

**Writing Clue's fields**

- HubSpot company: Atrium `clue_tier` tier_1 and `clue_id`; ATMA `clue_tier` tier_1.
- Salesforce: four contacts' `Clue_Id__c`; Carmel Clay `Clue_Tier__c` + `Clue_Id__c`.
- After the fix pass (`83ea71112`): Syracuse City School District `Clue_Tier__c` "Tier 1" +
  `Clue_Id__c` on **one card, one call** — both succeeded and read back (this was the
  `DUPLICATE_VALUE` finding below).
- After the fix pass (`52a84138e`): HubSpot contact Sandi Snead (created by Clue on a card) got
  `clue_id` through `HUBSPOT_PARTIALLY_UPDATE_CRM_OBJECT_BY_ID` — succeeded and read back.
- The agent refused to make up values: Rob Mangiarelli has no committee role in Clue's research, so
  it wrote none and said so.

**A field deleted in the CRM (founder deleted HubSpot company property `clue_tier`)**

- "Set Clue tier on ATMA Hotel Group in HubSpot" → refused "Clue's field Clue tier no longer exists
  in HubSpot; set up Clue's fields again."; registry `gone` with `companies.clue_tier`.
- The agent proposed the setup card again; allowed → "1 created, 8 already there"; registry back to
  `ready`; the wake turn proposed ATMA's tier again; allowed → written and read back.

**Possible duplicate (founder created a second Holly Herrera in Salesforce)**

- With the action named, the agent proposed `SALESFORCE_UPDATE_CONTACT` setting only
  `Clue_Possible_Duplicate__c` on `003jV00000F5nVhQAJ` to `003jV00000F7BNtQAN`; the card said
  "Mark 1 possible duplicate"; allowed → succeeded and read back. Nothing was merged.

## Findings

- **L4-1 — Two field changes on one Salesforce record failed (Important, FIXED `83ea71112`).**
  One composite call carried the record twice → both refused `DUPLICATE_VALUE`. Changes on one record
  are now merged into one entry (Salesforce composite and HubSpot company batch). Re-checked live.
- **L4-2 — HubSpot contact updates dropped Clue's fields (Important, FIXED `52a84138e`).**
  `HUBSPOT_UPDATE_CONTACTS` silently drops custom properties and `hs_buying_role`, so read-back
  failed (this also affected Phase 3's buying role). Contact updates now go through
  `HUBSPOT_PARTIALLY_UPDATE_CRM_OBJECT_BY_ID`. Re-checked live on Sandi Snead.
- **L4-3 — A direct "link these two as duplicates" request fails (FIXED `5acc1f44c`, Head of ABM v83 / crm-writing v6; re-checked live: asked plainly, the agent proposed `SALESFORCE_UPDATE_CONTACT` + `Clue_Possible_Duplicate__c` itself).** The exact
  action per CRM reaches the agent only in the `crm_possible_duplicate` refusal, which comes from a
  contact create. When the person asks directly, the agent guessed `link_duplicate` as the action,
  was refused `crm_write_not_allowed`, and told the person to link them by hand. Fix: one line in
  crm-writing (and the `crm_write_not_allowed` note) naming the action per CRM
  (`HUBSPOT_CREATE_OBJECT_ASSOCIATION` with Clue's label; `SALESFORCE_UPDATE_CONTACT` setting only
  `Clue_Possible_Duplicate__c`). Skill wording needs the founder's review; needs a re-mint.
  Related: the tool note says to link only records a refusal named, but a direct request with two
  CRM ids of one email was accepted — that is prompt judgement, not a code check (by design).
- **L4-4 — "This review request belongs to a different conversation" after a workspace switch
  (FIXED `72bec6309`, = Phase 2 L12; founder chose the self-reload; re-checked live with a switch in a second tab).** The page keeps the workspace it was first loaded with
  (`chat-gate.ts:546` compares the card's workspace against it); after switching workspaces in the
  same tab, cards read as another conversation until a full reload. Not CRM-specific.
- **L4-5 — A HubSpot contact create can't carry `clue_id` (FIXED `e9261082c`; re-checked live: Kimberly Furlong created with `clue_id` on one card, read back from HubSpot).** Salesforce creates add
  `Clue_Id__c` when ready; HubSpot creates don't, so Sandi took two cards (create, then the id on the
  wake turn) and the agent spent many steps working that out. Could add `clue_id` to HubSpot creates
  the same way.
- **L4-6 — The duplicate card doesn't name the person (FIXED `e9261082c`; live card: "Mark two records of Holly Herrera (…) as possible duplicates").** "Mark 1 possible duplicate" — the
  record label exists ("two records of Holly Herrera …") but the card's title line does not use it.
- **L4-7 — A wake turn was cut off by the stack restart (dev only).** The ATMA wake turn started as
  the workers restarted and ended without a reply; the write itself had already finished.

- **L4-8 — A harness retry error on a repaired proposal (minor, not CRM).** After a refused
  proposal the agent's corrected call failed once with "retry_of does not identify a failed
  attempt"; its next call went through. Owned by the agent harness, not this lane.

## Left in the test CRMs

HubSpot: the `clue` group and properties, the "Possible duplicate" label; Sandi Snead (contact
576692661964, Atrium); Kimberly Furlong (576723304126, Atrium); Clue fields on Atrium, ATMA, Rob, Sandi. Salesforce: the 6 Clue fields,
permission set `Clue_Fields` (`0PSjV000003qstpWAA`) and its assignment; the second Holly Herrera
(`003jV00000F7BNtQAN`, founder-made) linked both ways; Clue fields on Carmel Clay, Syracuse and
four contacts.
