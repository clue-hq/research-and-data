# CRM integration Phase 3 — first writes: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Head of ABM writes a project's research into the customer's CRM: target accounts into a
Clue list (HubSpot) or campaign (Salesforce) whose id Clue keeps, HubSpot's Target account and ICP
tier fields, buying-committee members as contacts, and missing companies/accounts — with the
personal-data rule R-8.7 enforced in code, not only in the skill.

**Architecture:** Everything rides the Phase 2 write path (`propose_crm_changes` → card → executor →
wake). Phase 3 adds: (1) a list registry in Postgres (`crm_list`, `crm_list_project`) and the
create-list / create-campaign actions that fill it; (2) one read tool, `read_crm_targets@1`, that
hands the agent a project's accounts and committee contacts already reduced to what R-8.7 allows,
each value with the claim it came from; (3) a check in prepare that every value written about a
person matches that read, so the agent cannot write a person field Clue did not research and clear;
(4) the `crm-writing` skill v2 and a catalog bump.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async + Alembic (Postgres), Composio REST v3.1,
Next.js/TypeScript (card wording only), pytest + `node:test`.

**Spec:** `docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md`
(§6.2, §6.8, §6.10, §12 item 3), `docs/superpowers/specs/crm-integration/rulings.md` (R-6.9, R-6.13,
R-6.17–R-6.19, R-7.1, R-8.1, R-8.3, R-8.7, R-11.7, R-11.11), the card spec
`docs/superpowers/specs/crm-integration/2026-10-22-crm-write-permission-card-design.md` (§5 wording),
and `docs/superpowers/specs/crm-integration/composio-api-notes.md`.

---

## Decisions for the founder (rule on these before Task 1 starts)

Each has my recommendation; the plan below is written for the recommendation. Record each ruling in
`rulings.md` as R-12.x before execution.

| # | Question | Recommendation | Why |
|---|---|---|---|
| D-1 | ARV2 has **no tier** — only `account.scoring.fit` (0–1) shown as High/Medium/Low (thresholds 0.70 / 0.40). What fills HubSpot's ICP tier? | **High → Tier 1, Medium → Tier 2, Low → Tier 3**, from the same thresholds the screens use; an account with no fit claim gets no tier change | One source of truth; what the person sees in Clue is what lands in the CRM |
| D-2 | "Work email only if verified" (R-8.7): ARV2 email status is `verified_smtp`, `catch_all_valid`, `invalid`, `unknown`, `unverified`; the screens treat `catch_all_valid` as usable too | **`verified_smtp` only.** No such email → no contact created (R-8.7 call 6) | Ruling says "only verified"; catch-all means the domain accepts anything |
| D-3 | What goes on the list? HubSpot lists hold one object type; Salesforce campaigns hold contacts/leads only, never accounts | **HubSpot: one company list per project ("Clue: <project>") holding the target accounts. Salesforce: one campaign per project holding the committee contacts Clue wrote** (accounts cannot be campaign members) | Matches design §6.8; the only shape each CRM allows |
| D-4 | Duplicate tagging (R-6.13) needs a schema change in the customer's CRM (HubSpot "Possible duplicate" association label; a Salesforce custom field, which is option B) | **Move duplicate links to Phase 4** with the other admin schema changes. Phase 3 keeps find-before-create (built) and records which CRM record each Clue entity maps to | Both paths are admin schema writes, which is Phase 4's whole subject |
| D-5 | The jurisdiction/use-class gate: ARV2 writes no `use_decision` and no `contact.jurisdiction`, so the existing gate has nothing to read | **Enforce what ARV2 records now**: the claim must be live, `outreach_safe` not false, `use_class` not `sensitive`, binding not `weak`; the jurisdiction gate joins when ARV2 records jurisdiction (the deferred privacy sprint) | Fails closed on every fact Clue has; no fabricated regime |
| D-6 | Persona → HubSpot `hs_buying_role` (multi-select). Values are not recorded anywhere yet | **champion → CHAMPION, economic_buyer → BUDGET_HOLDER, technical_evaluator → INFLUENCER, blocker → BLOCKER, user → END_USER**, confirmed against the portal's options in Task 1; Salesforce has no standard field — role is not written there in Phase 3 | HubSpot's documented options; Task 1 verifies before anything is built on them |

---

## Global Constraints

- Every CRM call goes through the Phase 2 gateway, allowlists and executor; no new write path.
- Nothing is written to a CRM without a card or a standing permission (R-6.3); creating a list or
  campaign is its own kind, `list_create`, offered "Always allow" like any kind (R-6.7).
- Person data written to a CRM (R-8.7): first and last name, job title, company link, buying role,
  work email only when `verified_smtp` (D-2), LinkedIn URL only from the contact record and only when
  the contact's claims are not `weak`; never phone, personal research, sensitive data or consent
  fields (R-8.1).
- Salesforce people are Contacts only, never Leads (R-6.17).
- Clue never deletes or merges CRM records (R-6.13); it removes only list/campaign members it added.
- A list or campaign belongs to one connection; a project may use several, a list may serve several
  projects (R-11.11).
- New Alembic revisions use hash ids, `down_revision` = the current single head, reversible
  downgrades with a populated round-trip test (the I-4 lesson).
- Every new flag goes in `.env.example` with its default (env parity rule).
- Skill and manual wording is founder-reviewed before it is written (standing rule); Task 8 shows the
  substance first.
- DB tests run only on `clue_nashville_crm_test`; nothing calls a real CRM except Task 1 and Task 9.
- No AI attribution in commits (repo CLAUDE.md).

## Review Focus

1. **A contact whose name is one word, or has three or more words** — first/last name must still be
   sensible (one word → last name only on Salesforce, which requires LastName; HubSpot firstname
   only). Test in Task 4.
2. **A Clue account whose domain differs in spelling from the CRM's** (`www.`, scheme, trailing
   slash) — find-before-create must match it (Salesforce host match exists since I-5; HubSpot
   `domain` is normalised by HubSpot). Test in Task 5.
3. **The stored list was deleted in the CRM** — the next add fails with HubSpot's
   `LIST_ID_DOES_NOT_EXIST`; Clue marks the stored list gone and the agent recovers by name, then
   proposes a new list (R-11.11 (4)). Test in Task 3.
4. **Two projects share one list** — removing members for project A must not touch members only
   project B asked for. Test in Task 2.
5. **A person value the agent typed itself** (an email from the web, a guessed LinkedIn URL) — refused
   per change as `crm_personal_data_not_allowed`, the rest of the batch proposes. Test in Task 5.

---

## File structure

| File | Responsibility |
|---|---|
| `alembic/versions/<hash>_crm_lists.py` | `crm_list`, `crm_list_project`, `crm_write.source_claim_ids`, `crm_write.clue_entity_id` |
| `platform/api/clue_api/crm/lists.py` (new) | the list registry: store, find for a project, link a project, mark gone |
| `platform/api/clue_api/crm/write_actions.py` | `list_create` kind; HubSpot company lists; the two create actions |
| `platform/api/clue_api/crm/read_actions.py` | three list reads on the read allowlist |
| `platform/api/clue_api/crm/targets.py` (new) | builds the R-8.7-reduced view of a project's accounts and contacts |
| `platform/api/clue_api/crm/target_tools.py` (new) | `read_crm_targets@1`, `find_crm_list@1`, `link_crm_list@1` |
| `platform/api/clue_api/crm/write_prepare.py` | the person-value check against `targets.py`; record claim ids |
| `platform/api/clue_api/crm/write_executor.py` | store created lists; stamp `clue_entity_id` on record links; list-gone handling |
| `apps/frontend/src/features/integrations/model/crm-write.ts` | card wording for `list_create` |
| `platform/agents/catalog/skills/crm-writing/v2/SKILL.md` + catalog files | the Phase 3 workflow |
| `docs/superpowers/specs/crm-integration/composio-api-notes.md` | verified shapes from Task 1 |

---

### Task 1: Verify the list, campaign and field shapes on both test CRMs (spike, no product code)

**Files:**
- Modify: `docs/superpowers/specs/crm-integration/composio-api-notes.md` (new section "Phase 3 shapes")
- Create: `scripts/crm_phase3_spike.py` (scratch-style, run by hand, uses the Composio gateway and the dev project's test accounts)

**Interfaces:**
- Produces: verified argument and answer shapes, written down verbatim (trimmed), for every action
  later tasks allowlist; the live option lists of `hs_buying_role`, `hs_is_target_account`,
  `hs_ideal_customer_profile`; Salesforce `CampaignMember.Status` values.

- [ ] **Step 1:** HubSpot (Conduit test portal), read-only first: `HUBSPOT_READ_ALL_PROPERTIES_FOR_OBJECT_TYPE` for companies and contacts → record the options of `hs_ideal_customer_profile`, `hs_is_target_account`, `hs_buying_role` (and whether `hs_buying_role` is multi-select). Confirm or correct D-6.
- [ ] **Step 2:** HubSpot lists: `HUBSPOT_SEARCH_CRM_LISTS` (empty portal answer), `HUBSPOT_CREATE_LIST` for a manual **company** list `Clue: spike`, `HUBSPOT_GET_CRM_LIST_BY_NAME` for it, `HUBSPOT_UPDATE_LIST_MEMBERSHIPS` add then remove one company (object type `0-2`), `HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS` for that company; then an add to list id `999999999` to record the `LIST_ID_DOES_NOT_EXIST` answer. Record the list's `processingType` value for manual vs dynamic.
- [ ] **Step 3:** Salesforce (Garner test org): `SALESFORCE_CREATE_CAMPAIGN` `Clue: spike`; SOQL `SELECT Id, Name, IsActive FROM Campaign WHERE Name = 'Clue: spike'`; `SALESFORCE_ADD_CONTACT_TO_CAMPAIGN` for one test contact (record the default member `Status` and the allowed values via `SELECT Label FROM CampaignMemberStatus WHERE CampaignId = …`); `SALESFORCE_REMOVE_FROM_CAMPAIGN`.
- [ ] **Step 4:** Clean up what the spike created (remove members; leave the two `Clue: spike` lists/campaigns and say so — Clue never deletes CRM records, R-6.13; the founder can delete them by hand).
- [ ] **Step 5:** Write the section in `composio-api-notes.md` (slug ✔ verified, arguments, answer shape, errors seen) and commit `Docs: CRM Phase 3 shapes verified on both test CRMs`. If a shape contradicts this plan (e.g. company lists need another action), stop and bring it to the founder before Task 2.

---

### Task 2: The list registry (migration + store)

**Files:**
- Create: `alembic/versions/<hash>_crm_lists.py`, `platform/api/clue_api/crm/lists.py`
- Test: `tests/db/test_crm_lists_migration.py`, `tests/api/test_crm_lists_db.py`

**Interfaces:**
- Produces (tables): `crm_list(list_id uuid pk, workspace_id, connection_id → workspace_integration_connection, provider, crm_object text CHECK in ('company','contact'), crm_list_id text, name text, kind text CHECK in ('hubspot_list','salesforce_campaign'), created_by_clue bool, created_by_write_id uuid null, gone_at timestamptz null, created_at)`, unique `(connection_id, crm_list_id)`; `crm_list_project(list_id → crm_list, project_id, workspace_id, linked_at, linked_by text CHECK in ('clue_created','person_named'))`, pk `(list_id, project_id)`; `crm_write.source_claim_ids uuid[] NOT NULL DEFAULT '{}'`, `crm_write.clue_entity_id text NULL`.
- Produces (Python, `crm/lists.py`): `@dataclass(frozen=True) class CrmList` (fields above); `async def store_list(conn, *, workspace_id, connection_id, provider, crm_object, crm_list_id, name, kind, created_by_clue, created_by_write_id, project_id) -> CrmList` (idempotent on `(connection_id, crm_list_id)`, links the project); `async def lists_for_project(conn, *, workspace_id, project_id, connection_id) -> list[CrmList]` (excludes `gone_at`); `async def link_project(conn, *, list_id, project_id, workspace_id, linked_by) -> None`; `async def mark_gone(conn, *, connection_id, crm_list_id) -> None`.
- Consumes: `writes.membership_link_id`, `writes.clue_added_members` (membership is still per list member in `crm_record_link`).

- [ ] **Step 1: Failing tests** — `test_a_created_list_is_stored_once_and_linked_to_its_project`; `test_a_list_serves_two_projects` (link a second project; both `lists_for_project` return it); `test_a_gone_list_is_not_offered`; `test_lists_are_per_connection` (same CRM id on another connection is another row); `test_members_added_for_one_project_are_not_removable_as_anothers` (Review Focus 4: `crm_record_link` list-member rows stay keyed by list, and the removal check in prepare refuses a member the batch's project never added — extend `clue_added_members` with `project_id` via the write's proposal); migration up→down→up with a populated row.
- [ ] **Step 2:** Run on the throwaway DB — FAIL (`relation "crm_list" does not exist`).
- [ ] **Step 3:** Write the migration and `crm/lists.py`; extend `writes.clue_added_members(conn, *, connection_id, list_ref, project_id: str | None = None)`.
- [ ] **Step 4:** Run → PASS; `alembic heads` shows one head.
- [ ] **Step 5:** Commit `feat(crm): Clue keeps its CRM lists and campaigns`.

---

### Task 3: Create-list / create-campaign actions, company lists, and list recovery

**Files:**
- Modify: `platform/api/clue_api/crm/write_actions.py`, `read_actions.py`, `write_prepare.py`, `write_executor.py`, `apps/frontend/src/features/integrations/model/crm-write.ts`
- Test: `tests/api/test_crm_write_actions.py`, `tests/api/test_crm_write_prepare_db.py`, `tests/api/test_crm_write_executor_db.py`, `apps/frontend/src/features/integrations/model/crm-write.test.ts`

**Interfaces:**
- Consumes: Task 1's verified shapes; `crm/lists.py` (Task 2).
- Produces: `WriteKind` gains `"list_create"`; allowlist entries `HUBSPOT_CREATE_LIST` (object `company` or `contact` from the list's object type id, `kind="list_create"`) and `SALESFORCE_CREATE_CAMPAIGN` (object `contact`); `HUBSPOT_UPDATE_LIST_MEMBERSHIPS` parses the object from the list's stored `crm_object` (company or contact) instead of hard-coding contact; read allowlist adds `HUBSPOT_GET_CRM_LIST_BY_NAME`, `HUBSPOT_SEARCH_CRM_LISTS` (and `SALESFORCE_LIST_CAMPAIGNS` if Task 1 found it useful; Campaign SOQL already works). Executor: a succeeded `list_create` calls `lists.store_list(...)` with the proposal's project; a membership change answered `LIST_ID_DOES_NOT_EXIST` calls `lists.mark_gone(...)` and fails the change with `failure_kind="other"`, `crm_message` "The list no longer exists in HubSpot; find it by name or create it again." Card wording (spec §5): "Create the list "{name}"" / "Create the campaign "{name}"" and the always-allow phrase "creating Clue lists" / "creating Clue campaigns".

- [ ] **Step 1: Failing tests** — `test_create_list_is_a_list_create_change` (both CRMs; HubSpot creates a **manual** list, a dynamic one is refused `crm_write_not_parsable` "Clue creates manual lists only"); `test_company_list_membership_parses_companies`; `test_a_created_list_is_stored_for_the_project` (executor, fake gateway answers with the Task-1 shape); `test_a_deleted_list_is_marked_gone_and_the_change_fails` (Review Focus 3); card model tests for the two titles and phrases.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. A `list_create` change has no before-value read and no overwrite; prepare refuses a second create of the same name on the same connection when `crm_list` already holds a live list of that name (`crm_list_exists`, message names the stored id).
- [ ] **Step 4:** Run → PASS; run all `tests/api/test_crm_write*`; frontend touched tests + `npm run lint`.
- [ ] **Step 5:** Commit `feat(crm): create a Clue list or campaign and keep its id`.

---

### Task 4: `read_crm_targets@1` — a project's accounts and committee, reduced to what R-8.7 allows

**Files:**
- Create: `platform/api/clue_api/crm/targets.py`, `platform/api/clue_api/crm/target_tools.py`
- Modify: toolbelt registration (where `propose_crm_changes@1` is registered — grep), not granted until Task 8
- Test: `tests/api/test_crm_targets_db.py`

**Interfaces:**
- Consumes: `project_account` + `account_entity` (exclude `merged_into`); claims `account.scoring.fit` (D-1), `contact.persona`, `contact.role_on_committee`, `contact.current_title`, `core.work_email`; `contact_entity.full_name`, `.linkedin_url`; the committee rule `committee_members_for_accounts` (`platform/api/clue_api/arv2/display/gather.py:288-359`); `crm_record_link` (which CRM record each Clue entity already maps to); `settings.arv2_fit_high_threshold` / `arv2_fit_medium_threshold`.
- Produces (pure, `targets.py`):
  - `@dataclass(frozen=True) class TargetValue: value: str; claim_ids: tuple[UUID, ...]` (empty tuple only for entity columns: name, domain, LinkedIn).
  - `@dataclass(frozen=True) class TargetAccount: account_entity_id: str; name: str; domain: str | None; fit_band: Literal["high","medium","low"] | None; hubspot_icp_tier: TargetValue | None; crm_record_id: str | None`.
  - `@dataclass(frozen=True) class TargetContact: contact_entity_id: str; account_entity_id: str; first_name: TargetValue | None; last_name: TargetValue; job_title: TargetValue | None; buying_role: TargetValue | None; work_email: TargetValue | None; linkedin_url: TargetValue | None; withheld: tuple[str, ...]; crm_record_id: str | None`. `withheld` names each field left out and why, in plain words ("email: not verified (catch_all_valid)", "LinkedIn: identity not confirmed", "title: marked not safe for outreach").
  - `def split_name(full_name: str) -> tuple[str | None, str]` (Review Focus 1: one word → `(None, word)`; else first word / the rest).
  - `def hubspot_tier(fit: float | None, *, high: float, medium: float) -> str | None` (`tier_1` / `tier_2` / `tier_3` / None).
  - `def hubspot_buying_role(persona: str | None) -> str | None` (D-6 table, values as Task 1 verified).
  - `async def project_targets(conn, *, workspace_id, project_id, connection_id, provider, account_ids: Sequence[str] | None) -> tuple[list[TargetAccount], list[TargetContact]]`.
- Produces (tool): `ReadCrmTargetsTool` name `read_crm_targets`, version 1, `READ`/`EFFECT_FREE`; input `{project_id, account_ids?: list[str] ≤ 200, include_contacts: bool = true, offset, limit ≤ 200}`; output `{accounts, contacts, total_accounts, connected_crm}` using the dataclasses above.

R-8.7 / D-2 / D-5 reductions (each a test): a value is offered only from a **live** claim (not superseded/rejected) whose `use_class` is not `sensitive`, `outreach_safe` is not false, and `identity_binding` is not `weak`; work email only when `core.work_email.status == "verified_smtp"`; LinkedIn only from `contact_entity.linkedin_url` and only when every offered claim of that contact is not `weak`; never phone, interests, posts, facets (`contact.facet.*` is never read).

- [ ] **Step 1: Failing tests** — `test_tier_follows_the_fit_bands_the_screens_use` (0.81 → tier_1, 0.55 → tier_2, 0.10 → tier_3, none → None); `test_split_name_handles_one_and_many_words`; `test_only_a_verified_smtp_email_is_offered` (`catch_all_valid` is withheld with its reason); `test_a_sensitive_or_unsafe_or_weak_claim_is_withheld`; `test_linkedin_is_withheld_when_any_claim_is_weak`; `test_contacts_come_from_the_committee_rule`; `test_an_account_already_in_the_crm_carries_its_record_id`; `test_workspace_isolation` (another workspace's project returns nothing).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `targets.py` and the tool.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(crm): read a project's CRM-ready accounts and committee`.

---

### Task 5: Prepare checks every person value against the targets (R-8.7 in code)

**Files:**
- Modify: `platform/api/clue_api/crm/write_tools.py` (`CrmChangeInput.clue_entity_id: str | None`), `write_prepare.py`, `writes.py` (store `source_claim_ids`, `clue_entity_id`)
- Test: `tests/api/test_crm_write_prepare_db.py`, `tests/api/test_crm_propose_db.py`

**Interfaces:**
- Consumes: `targets.project_targets` (Task 4), `RefusedChange` / per-change refusals (R-11.7 code path).
- Produces: a change that creates or updates a **person** (`create_contact`, a `field_update` on a contact) must name `clue_entity_id` (a contact of this workspace) — otherwise refused per change `crm_personal_data_not_allowed` ("Name the Clue contact this is about"). For each person field it writes, the value must equal the `TargetContact` value for that field (case-insensitive for email, whitespace-normalised otherwise), else refused per change `crm_personal_data_not_allowed` naming the field and the reason from `withheld` or "not what Clue researched". A company `field_update` or `create_company` may name `clue_entity_id` (an account); when it does, `hs_ideal_customer_profile` must equal `TargetAccount.hubspot_icp_tier` and `hs_is_target_account` may be set true. The change's claim ids are stored on `crm_write.source_claim_ids`, and `clue_entity_id` on `crm_write.clue_entity_id`. `source_ref` stays as free text for the agent's own note.

- [ ] **Step 1: Failing tests** — `test_a_person_change_without_a_clue_contact_is_refused`; `test_an_email_the_agent_typed_is_refused_but_the_rest_proposes` (Review Focus 5); `test_a_catch_all_email_is_refused_with_its_reason`; `test_a_matching_contact_create_proposes_with_its_claim_ids`; `test_a_company_tier_must_match_the_fit_band`; `test_a_domain_spelled_differently_finds_the_existing_company` (Review Focus 2 — HubSpot `domain` search, Salesforce host match); `test_a_contact_of_another_workspace_is_refused`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Reuse the R-11.7 per-change refusal list; add `crm_personal_data_not_allowed` to `tool_notes.yaml` under `propose_crm_changes` (wording reviewed in Task 8).
- [ ] **Step 4:** Run → PASS; all `tests/api/test_crm_write*` and `test_crm_propose_db`.
- [ ] **Step 5:** Commit `feat(crm): a person value reaches the CRM only as Clue researched and cleared it`.

---

### Task 6: The executor records which Clue entity each CRM record is

**Files:**
- Modify: `platform/api/clue_api/crm/write_executor.py`, `writes.py`
- Test: `tests/api/test_crm_write_executor_db.py`

**Interfaces:**
- Consumes: `crm_write.clue_entity_id` (Task 5).
- Produces: on a succeeded create **or update**, `record_link(..., clue_entity_id=write.clue_entity_id)` (an update links an existing CRM record to its Clue entity; `created_by_clue` stays false for updates); `targets.project_targets` then reports `crm_record_id` (Task 4's `test_an_account_already_in_the_crm_carries_its_record_id` gets its live producer). The finished wake message names created records with their ids (built in L9) and adds "Linked N Clue records to their CRM records." when any update linked one.

- [ ] **Step 1: Failing tests** — `test_a_created_contact_is_linked_to_its_clue_contact`; `test_an_updated_company_is_linked_but_not_marked_created_by_clue`; `test_a_failed_write_links_nothing`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(crm): Clue remembers which CRM record each account and contact is`.

---

### Task 7: `find_crm_list@1` and `link_crm_list@1`

**Files:**
- Modify: `platform/api/clue_api/crm/target_tools.py`
- Test: `tests/api/test_crm_list_tools_db.py`

**Interfaces:**
- Consumes: `crm/lists.py` (Task 2), the read allowlist entries (Task 3), the Composio gateway.
- Produces:
  - `FindCrmListTool` `find_crm_list@1` (`READ`, `EFFECT_FREE`): input `{project_id, name?: str}`; returns the project's stored live lists first; with `name`, looks the list up in the CRM by exact name (HubSpot `HUBSPOT_GET_CRM_LIST_BY_NAME` for the object type; Salesforce Campaign SOQL) and returns `{crm_list_id, name, object, manual: bool, stored: bool}`; when a stored list is gone it says so (R-11.11 (4)).
  - `LinkCrmListTool` `link_crm_list@1` (`WRITE` to Clue's own database only, `DOMAIN_IDEMPOTENT`): input `{project_id, crm_list_id}`; verifies the list exists in the CRM and is manual (HubSpot) / a campaign (Salesforce), stores it `created_by_clue=false`, `linked_by='person_named'`; refuses a dynamic list `crm_list_not_manual` and an unknown id `crm_list_not_found`. It writes nothing to the CRM, so it needs no card.

- [ ] **Step 1: Failing tests** — `test_find_returns_the_stored_list_first`; `test_find_by_name_in_the_crm`; `test_a_gone_list_is_reported_as_gone`; `test_link_stores_a_named_manual_list_not_created_by_clue`; `test_link_refuses_a_dynamic_list`; `test_link_refuses_another_workspaces_project`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(crm): find a project's list and link one the person names`.

---

### Task 8: `crm-writing` v2, Head of ABM v78, recipe 38, manual re-mint

**Files:**
- Create: `platform/agents/catalog/skills/crm-writing/v2/SKILL.md`, `platform/agents/catalog/profiles/head-of-abm/v78/profile.yaml`, `platform/execution/recipes/recipe0-stage0-v38.json`
- Modify: `agent_registry_wiring.py` (grant `read_crm_targets`, `find_crm_list`, `link_crm_list`; active v78), `recipe_contracts.py`, `recipe_wiring.py`, `conversation_turns.py` (`CONVERSATION_RECIPE_VERSION = 38`), `stage0_recipe.py`, `chat/composer_context.py`, `platform/agents/catalog/manual/tool_notes.yaml`, the pinning tests; manual re-mint `uv run python -m clue_api.manual_build --write`
- Test: `tests/api/test_agent_registry_wiring.py`, `tests/api/test_recipe_contracts.py`, `tests/agents/test_catalog.py`, `tests/agents/test_manual_builder.py`, `tests/agents/test_manual_drift.py`, `tests/agents/test_tool_authority_audit.py`

**Interfaces:**
- Consumes: the three new tools (Tasks 4, 7) and the new refusals (`crm_personal_data_not_allowed`, `crm_list_exists`, `crm_list_not_manual`, `crm_list_not_found`).

- [ ] **Step 1: Show the founder the skill substance** (v1 plus): start every CRM write for a project from `read_crm_targets`; the project's list: `find_crm_list` first, then propose "Create the list 'Clue: <project name>'" only when none exists, or `link_crm_list` when the person names one; target accounts → the list (HubSpot companies) / committee contacts → the campaign (Salesforce); Target account + ICP tier from the targets (never computed by the agent); committee contacts: create only those the targets offer with a verified email, pass `clue_entity_id`, never fill a withheld field — tell the person what was withheld and why; an account already in the CRM is updated, not created; batch by decision, one card. **Write only the approved wording.**
- [ ] **Step 2:** Bump the catalog (v78, recipe 38, manual), pinning tests' expected values.
- [ ] **Step 3:** Run the six test files → PASS.
- [ ] **Step 4:** Commit `feat(crm): Head of ABM v78 writes a project's research into the CRM`.

---

### Task 9: Live check on both test CRMs

**Files:** `docs/superpowers/specs/crm-integration/status.md`, `rulings.md` (any new decision), a findings note `docs/superpowers/specs/crm-integration/<date>-phase-3-live-check-findings.md`, `_memory/<date>-crm-integration-phase3.md`

- [ ] **Step 1:** Migrate the nashville stack DB in place; restart workers and APIs by double fork (never inside a stoppable task).
- [ ] **Step 2 (Conduit AI, HubSpot):** in a project with researched accounts: "put our target accounts into HubSpot with their tiers" → the agent reads targets, finds no list, proposes create-list + add companies + Target account + ICP tier on one card; allow; check in HubSpot (read back) and in `crm_list`; then "add the buying committee as contacts" → only verified-email contacts proposed, withheld fields named; allow one, decline the rest; ask to remove one company from the list (only Clue-added members removable).
- [ ] **Step 3 (Garner Health, Salesforce):** the campaign flow with committee contacts; one contact whose account is not in Salesforce → the agent proposes the missing account first (R-6.18).
- [ ] **Step 4:** Delete a test list in HubSpot by hand (founder), then ask to add an account → "the list no longer exists" → recovery by name → new list proposed.
- [ ] **Step 5:** Record results, findings and cost; commit `Docs: CRM Phase 3 live check`.

---

### Task 10: One card can use the records it creates (R-12.11, live-check finding L-1)

Added 2026-10-24 after the live check (founder chose option a; design and skill lines approved in chat).

**Files:**
- Modify: `platform/api/clue_api/crm/write_prepare.py` (parse/check record references), `platform/api/clue_api/crm/write_executor.py` (send creates first, fill ids, skip dependents), `platform/api/clue_api/crm/write_actions.py` (where the reference may appear), `platform/api/clue_api/crm/writes.py` if a column/helper is needed, `platform/agents/catalog/manual/tool_notes.yaml`
- Create: `platform/agents/catalog/skills/crm-writing/v3/SKILL.md` (v2 + the two approved lines), Head of ABM v79 / recipe 39 / manual re-mint, following Task 8's pattern (commit `2190d64ce`)
- Test: `tests/api/test_crm_write_prepare_db.py`, `tests/api/test_crm_write_executor_db.py`, the Task 8 pinning tests

**Interfaces:**
- Consumes: R-12.7's `new:<list name>` (`NEW_LIST_PREFIX`, `new_list_name`, `_with_list_objects` in prepare; the list-id fill/skip in the executor, around `write_executor.py:996` and `:1590–1640`).
- Produces: record references `new:company:<domain>` (a HubSpot company or Salesforce account the same proposal creates) and `new:contact:<email>` (a person the same proposal creates). Matching is case- and whitespace-insensitive against the create's domain (HubSpot `domain` / Salesforce `website` host) or email.

**Where a reference may appear (and nowhere else):**
- HubSpot list add (`HUBSPOT_UPDATE_LIST_MEMBERSHIPS` `record_ids`, one record per change) → `new:company:<domain>`.
- HubSpot person create (`HUBSPOT_CREATE_CONTACT` `associations` company id) → `new:company:<domain>`.
- Salesforce person create (`SALESFORCE_CREATE_CONTACT` `account_id`) → `new:company:<domain>`.
- Salesforce campaign add (`SALESFORCE_ADD_CONTACT_TO_CAMPAIGN` `contact_id`) → `new:contact:<email>` (the campaign may itself be `new:<name>`).

**Behaviour:**
- Prepare: a reference that matches no create on the same proposal is refused on its own (`crm_write_not_parsable`, plain message naming the reference). A person's company link that points at `new:company:…` still passes the R-8.7 person checks (the link is the company-link field). The card label uses the referenced record's name, never the `new:` string.
- Executor order: list/campaign creates and company/account creates first, then person creates, then list/campaign adds. After each create (or a create that found the record already there — use the found id), fill its id into every undecided change that references it, the same way new list ids are filled.
- A change whose referenced create failed, did not land, or was not ticked on the card is not sent: `skipped` with the message "The <company|person> it needs was not created, so it was not sent." Nothing it depends on is retried by itself.

- [ ] **Step 1: Failing tests (prepare):** an add to `new:company:<domain>` with a matching create passes and its card label is the company name; one with no matching create is refused `crm_write_not_parsable`; a Salesforce contact create with `account_id = new:company:<domain>` passes; a campaign add with `contact_id = new:contact:<email>` passes; a reference in any other field is refused.
- [ ] **Step 2: Failing tests (executor, fake CRM):** (a) HubSpot: create company + add `new:company` to a new list on one proposal → company created, its id filled, add sent with that id, both succeeded; (b) HubSpot: create company + create person linked `new:company` → person created with the association to the new id; (c) Salesforce: create account + create contact (`account_id` reference) + create campaign + add `new:contact` to `new:<campaign>` → all four in order with filled ids; (d) the company create fails → its dependent add and person are `skipped` with the message above, never sent; (e) the company create unticked on the card → same; (f) the create finds the company already exists → the found id is filled and the dependents are sent.
- [ ] **Step 3:** Implement until Steps 1–2 pass; keep every existing CRM test green.
- [ ] **Step 4:** crm-writing v3 = v2 plus exactly these founder-approved lines (2026-10-24): in §3b point 5, add "When a company or person is not in the CRM yet, put its create and everything that needs it on the same card: refer to it as `new:company:<domain>` or `new:contact:<email>`, spelled exactly like the create."; in §3b point 2, add "Add one record per change." Tool notes for `propose_crm_changes` name the two references. Mint Head of ABM v79, recipe 39, re-mint the manual (Task 8's pattern); pinning tests updated.
- [ ] **Step 5:** Run the CRM suites, the six Task 8 test files, `test_toolbelt_wiring.py`, `manual_build --check` → PASS. Commit `feat(crm): one card can use the records it creates (R-12.11)`.

---

### Task 11: Clean names, readable card labels, no system message as the person's words (R-12.12–R-12.14; live-check L-5, L-6, L-7)

Added 2026-10-24 (founder approved; runs after Task 10 — same files).

**Files:**
- Modify: `platform/api/clue_api/crm/targets.py` (`split_name` → clean then split), `platform/api/clue_api/crm/write_prepare.py` (compare against the cleaned name; labels), `platform/api/clue_api/crm/write_answer.py` (card payload names), `apps/frontend/src/features/integrations/model/crm-write.ts` (+ test) if the title is built there
- Create: `platform/agents/catalog/skills/stage0-interview/v<next>/SKILL.md` with the one added line; Head of ABM next version / recipe next / manual re-mint (Task 8's pattern)
- Test: `tests/api/test_crm_targets_db.py` (or a unit test file for the name cleaner), `tests/api/test_crm_write_prepare_db.py`, the card payload tests, `crm-write.test.ts`, the pinning tests

**Name cleaning (R-12.12):** drop everything from the first comma; drop one leading honorific from {Dr., Dr, Mr., Mr, Mrs., Mrs, Ms., Ms, Miss, Prof., Prof, Rev., Rev} (case-insensitive); drop trailing {PhD, Ph.D., MD, M.D.}; keep Jr./Sr./II/III/IV in the last name; then split at the first space (one word → last name only). Cases: "Dr. Holly Herrera" → ("Holly", "Herrera"); "Bethany Maciel, MBA, SHRM-CP" → ("Bethany", "Maciel"); "John Smith Jr." → ("John", "Smith Jr."); "Jane Doe PhD" → ("Jane", "Doe"); "Madonna" → (None, "Madonna"); "Dr." alone → keep the raw name rather than produce an empty one.

**Labels (R-12.13):** the card's group title and rows name a list/campaign by its stored `crm_list.name` (or the name of a list/campaign the same card creates), and a field value that is a company/account id by that company's name when Clue knows it (record link label, a create on the same card, or the before-read); otherwise the id. Expected titles: 'Add 10 companies to the list "Clue: Conduit AI hotel operators"', 'Add 4 contacts to the campaign "Clue: US employer benefits"', 'Set "Primary Associated Company ID" on 1 contact' with the row value "Atrium Hospitality".

**Skill line (R-12.14, wording waived from review):** in stage0-interview, where `record_interview_answer` is taught, add: "Only the person's own words are recorded. A message Clue wrote — a wake-up after CRM changes, a finished discovery, a connected CRM — is never recorded as an interview answer."

- [ ] **Step 1:** Failing tests for the six name cases, the prepare comparison against the cleaned name, and the three label cases (backend payload + frontend title).
- [ ] **Step 2:** Implement until green; keep every CRM test green.
- [ ] **Step 3:** Skill line; mint the next Head of ABM / recipe / manual; pinning tests.
- [ ] **Step 4:** Run the CRM suites, the Task 8 test files, `test_toolbelt_wiring.py`, `manual_build --check`, and the frontend gate for `crm-write` (`npm run lint` + the vitest file) → PASS. Commit `fix(crm): clean names, readable card labels, no system message as the person's words`.

---

### Task 12: Deleted lists, cards that cannot go missing, no internal ids, live card progress (R-12.15–R-12.18; live-check L-12, L-13, L-15, L-16)

Added 2026-10-24 after the re-run (founder approved).

**Files:**
- Modify: `platform/api/clue_api/crm/write_executor.py` (gone-list recognition), the agent finalize path (`platform/api/clue_api/agent_runtime_wiring.py` / `agent_execution_wiring.py` / `agent_turn_wiring.py` — wherever `open_gate_refs` is turned into the turn's gate links), `platform/api/clue_api/crm/write_tools.py` (`crm_write_log` output), `apps/frontend/src/features/projects/hooks/use-crm-proposal-progress.ts` (+ the chat controller seam for the wake), `platform/agents/catalog/manual/tool_notes.yaml`
- Create: `platform/agents/catalog/skills/crm-writing/v4/SKILL.md` (v3 + one sentence); Head of ABM next / recipe next / manual re-mint (Task 8's pattern)
- Test: `tests/api/test_crm_write_executor_db.py`, the finalize/gate tests, `crm_write_log` tests, a frontend test for the hook

**L-12 / R-12.15:** HubSpot answered an add to a deleted list with "Attempted to modify membership for deleted lists: [PortalListId{portalId=…, listId=18}]; Aborting operations." (failure kind recorded `not_found`). The executor's gone-list handling (`_fail_gone_list`) must treat this answer like a not-found list: mark the kept `crm_list` gone, and give every change of that list in the call the existing gone message. Test with that exact response text.

**L-13 / R-12.16:** when a turn ends `awaiting_input` (or any status that shows cards), every `agent_gate` this turn created that is still unanswered is added to the turn's open gate refs if the agent left it out, so its gate part is emitted and the card shows. No duplicates when the agent did list it. Every gate kind, not only `crm_write_permission`. Test: a turn whose finalize carries only a user message but which created a CRM proposal gate → the gate part is emitted / the gate is linked.

**L-15 / R-12.17:** `crm_write_log` results mark `write_id`/`proposal_id` as internal (a field description or note: "for undo only, never shown to the person"); crm-writing v4 = v3 plus exactly: "Never show the person Clue's write or proposal ids; name the record and what changed instead." (founder-approved) in §8 (the write log and undo). Mint the next Head of ABM / recipe / manual.

**L-16 / R-12.18:** `useCrmProposalProgress` keeps polling while the page is hidden at 15 000 ms (2 000 ms when visible) instead of stopping; and the card re-reads at once when the chat receives the proposal's "changes finished" wake-up (a derived `crm_writes_finished` turn for that thread — find the seam in the chat controller / thread stream). Test both.

- [ ] **Step 1:** Failing tests for each of the four.
- [ ] **Step 2:** Implement; keep every CRM, gate and chat test green.
- [ ] **Step 3:** Skill sentence; mint; pinning tests.
- [ ] **Step 4:** Run the CRM suites, the gate/finalize tests, the Task 8 test files, `test_toolbelt_wiring.py`, `manual_build --check`, the frontend tests for the hook and `npm run lint` → PASS. Commit `fix(crm): deleted lists, cards that cannot go missing, no internal ids, live card progress`.

---

## Not in this plan (and why)

- Duplicate links (R-6.13): Phase 4 per D-4.
- Clue's own fields (option B) and `clue_fields_setup`: Phase 4.
- Per-workspace throttle (R-7.3) and the Salesforce field coverage design A (R-11.9): unchanged backlog.
- The open chat-card bugs L12 / L14 and the deferred Phase 1 paths: noted in the Phase 2 findings,
  set aside by the founder.
