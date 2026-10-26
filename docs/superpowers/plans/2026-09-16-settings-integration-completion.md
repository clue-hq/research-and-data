# Settings integration completion plan — 2026-09-16

**Status: Research fields UI implemented after preview approval; Pages decisions and remaining live acceptance stay open.**
Originally prepared against Irvine's
`settings-page` at `5bd1a66c1`, after rebasing onto local `research-streaming` at `440b6a7db`.
This plan concerns Settings and its actual consumers, not a rewrite of the platform.

**Product specification:** [Settings integration design](../specs/archive/2026-09-15-settings-integration-design.md).
**Implemented API contract:** [Settings contract](../../../apps/frontend/docs/api-contracts/settings.md).
**Original discussion:** [_memory exploration](../../../_memory/2026-09-14-settings-integration-exploration.md).

The numbered phases below track implementation and remaining acceptance. The progress table
records the current evidence; completed code does not by itself satisfy the live exit gates.

## Implementation progress — 2026-09-16

The founder authorized implementation of this plan. Recommendations D1–D8 and backend-first
scheduling are applied. The founder approved the Research fields preview and reuse of existing
Settings primitives on 2026-09-16; the live management screen is now implemented. Pages' remaining
contract choices are still unanswered.

| Phase | Current state |
| --- | --- |
| 0 | Checkout/design pin preserved; D1–D8 and Research fields visual approval recorded; Pages decisions pending |
| 1 | Permission/profile/non-manager-role changes implemented; automated checks pass; browser acceptance in progress |
| 2 | Registry and migration implemented; trigger, collision, isolation, concurrency and rollback tests pass |
| 3 | All three catalog callers scoped; lenient retirement protection implemented; existing instructions reused |
| 4 | API plus Zod/read/mutation repository implemented; lifecycle and four-role tests pass |
| 5 | Account/contact values and scoped evidence implemented; retirement/subject/workspace tests pass |
| 6 | Approved preview implemented with live reads/create/edit/retire, permissions, legacy redirects and responsive layout; 2,298 frontend tests and build pass |
| 7 | 496 backend tests from prior checkpoint; 2,298 current frontend tests and build pass; Irvine upgraded; Profile and invitation acceptance verified; Research fields create/edit/reload verified; live retirement confirmation pending, generated research and remaining lifecycle walk open |
| 8 | Pages defaults/snippets/fallback/form contract still awaiting review; no publisher changes made |

These statuses report code and completed evidence separately. Unchecked acceptance items below
remain work to complete, rather than a claim that all listed features are release-ready.

## 1. Outcome and scope

An owner/admin can manage workspace research instructions in Settings, and subsequent account and
person research actually consumes those instructions. Claims remain workspace-private, visible
through the appropriate account/contact read surfaces, and attributable to evidence. Retiring a
field removes it from future research and current custom columns without deleting past evidence.
Existing Profile, Workspace and Members functionality continues working through the real backend.

The latest founder decisions are binding:

- Suspended members remain visibly **Suspended**, read-only. No re-admit action is added for them.
- Retrying failed/rate-limited invitation delivery remains **revoke the pending invitation, then
  invite again**. No resend endpoint or hidden token rotation is added.
- Pages and Billing remain accessible dummy frontends for now, without blocking overlays.
- **Pages is required for V1.** Its implementation is a separate required phase below; a working
  dummy does not complete it or remove it from the release checklist.
- Connections, MCP server and Integrations retain the accepted inert previews.
- Data model remains accessible until Research fields replaces it. Do not restore its overlay.
- Platform field definitions are read-only; workspace field management is owner/admin only.
- No account/contact value editing, project-local custom fields, avatar uploads, new viewer-role
  control, website/rebuild flow, payments integration, or invented contact-field presentation.

## 2. Current implementation and concrete gaps

| Area | Current code | Work still required |
| --- | --- | --- |
| Settings shell | Catch-all route, navigation/profile menu, shared confirmation card and authenticated repositories exist | Preserve route/error behavior and verify the final screens against the pinned design |
| Profile | Own-name/display-name persistence, autosave and shell provider exist | Remove the legacy profile derivation still returned by the project accounts route |
| Workspace | Real name/logo/website read and name mutation exist | Use the specified `workspace.manage_settings` authority instead of borrowing member management |
| Members | Real reads, role/remove/re-admit/revoke actions, Clerk adapter and acceptance path exist | Finish real delivery/acceptance proof and full role/lifecycle browser walk; preserve the two accepted rulings |
| Research fields | Accessible Data model fixture, no management API/UI | Implement registry changes, API, workspace catalogs, result projections and the redesigned UI |
| Accounts custom columns | Variable-column rendering exists; backend selects only `pack='client'` definitions | Admit account research fields, use their labels, retain scope/retirement rules and connect evidence |
| Contacts | Real claims feed fixed chips and generated contact pages | Provide a defined payload for custom research values; do not assume every claim is automatically returned |
| Pages | Editable-looking static form; real design publishing machinery exists elsewhere | Define and integrate workspace defaults into the existing publisher, then bind the approved Settings form |
| Billing | Static plan/credits and controls | Keep the dummy by ruling; usage-only billing remains a separately scheduled follow-up |

### Source map used for this plan

| Boundary | Existing files / symbols |
| --- | --- |
| Settings API and transactions | `platform/api/clue_api/frontend_read/settings.py`: `principal_for`, `lock_manager`, `register_settings_routes` |
| Auth and invitations | `platform/auth/clue_auth/policy.py`, `store.py`, `provisioning.py`, `providers/clerk_api.py`; `platform/api/clue_api/auth_wiring.py` |
| Settings frontend | `apps/frontend/src/features/settings/{components,config,data,hooks,model}`; `src/app/(protected)/settings/[[...section]]/page.tsx` |
| Shared profile and remaining legacy consumer | `apps/frontend/src/app/(protected)/layout.tsx`; `src/app/api/projects/[projectId]/accounts/route.ts`; `features/accounts/data/workspace-profile.repository.ts` |
| Workspace registry | `subsystems/research/clue_research/claimstore/registry.py`: `ResolvedFieldDefinition`, `get_effective_field`, `list_effective_fields`, `register_workspace_field`, `retire_workspace_field`, `check_claim_writable` |
| Original registry constraints | `alembic/versions/282b9c7278c2_tenant_local_dynamic_client_kb_fields.py`; subsequent research-scope/product-scope/presentation migrations |
| Catalog composition | `platform/api/clue_api/arv2/account_research_store.py`, `account_research_driver.py`, `account_research_launch.py`, `account_research_catalog.py`, `structuring_client.py` |
| Claim insertion | `platform/api/clue_api/arv2/claim_writer.py`; `account_research_tools.py`: `ToolRuntime.write`, `write_each` |
| Result projections | `platform/api/clue_api/frontend_read/{v1_shared,contract_v1,account_detail,contacts}.py`; frontend account/contact Zod models and account table |
| Existing publisher | `subsystems/clue-design/apps/api/lumen_api/{main,web_export,design_store}.py`, `toolbelt/publishes.py` |

### Findings that change the original implementation checklist

1. **The database rejects all field updates.** The original migration installs
   `workspace_field_definition_immutable`, whose function always raises on UPDATE. Adding an
   update helper alone cannot implement editable research descriptions. `pack` also has a
   **NOT NULL** constraint; splitting its CHECK alone cannot permit the specified null value.
2. **Retirement can fall into unknown-field registration.** Effective lookup excludes retired
   workspace definitions; the lenient writer handles `UnknownFieldError` by registering a global
   proposed field. A job holding an old catalog could therefore attempt to recreate a retired
   key globally. This is a code-path finding, not a reproduced live incident. The spec's
   statement that the lenient writer needs no change is unsafe for the new lifecycle.
3. **There are three catalog call sites.** Account composition and person composition in the
   driver, plus the direct person-launch path, must all supply the workspace. Updating only the
   driver misses a production path.
4. **Description delivery already exists.** Both context builders receive
   `catalog_menu_text(catalog)`, and the structuring client uses the same catalog. Although the
   state-read tools return open field keys, a new prompt mechanism is unnecessary. Verify the
   existing description path with workspace entries rather than duplicating it.
5. **Storage does not imply evidence access.** `AccountCustomField` has no claim identifier.
   Account evidence access currently depends on the stored overview's cited IDs; contact detail
   returns fixed fields plus generated display/evidence. A custom claim need not be cited by
   either generated page. The promised custom-field evidence and contact payload need explicit
   projection work.
6. **Publishing is not absent.** The design service already owns publish revisions, rollback,
   public paths and durable noindex. Pages Settings needs to connect workspace defaults to that
   machinery, not create another publisher.

## 3. Contract amendments to settle before implementation

These recommendations were accepted for implementation by the founder’s request to proceed with
this plan on 2026-09-16. The two member rulings above remain unchanged. The separate design/Pages
questions following the table are still open.

| ID | Recommendation | Why / dependency |
| --- | --- | --- |
| D1 | Allow only research-row label/description updates with an exact version increment; retain immutable identity, shape, scope and creation metadata, and keep Client-KB rows immutable | Required to implement spec §9.4 safely; phase 2 |
| D2 | Treat retired/erased workspace keys as lifecycle refusals, never as unknown keys eligible for global proposal registration. Prevent global/workspace key collisions in both registration directions under a shared lock discipline | Required to uphold retirement and tenant-local vocabulary; phases 2–3. This is a narrow safety correction, not the broader redesign of agent-proposed fields |
| D3 | Edits take effect when a job is next composed; do not mutate an in-flight context. Retirement blocks subsequent writes once its transaction commits; existing claims stay readable. Model-produced batches report the rejected field through their existing per-claim failure receipts | Defines race behavior; avoid making one retired custom field discard unrelated model-produced claims |
| D4 | Preserve existing Client-KB custom-column behavior while adding active account research rows; never include contact research fields on account rows | The spec's replacement filter would otherwise remove an existing supported projection; phase 5 |
| D5 | Add explicit custom-field claim references to the read contract. Reuse the existing evidence drawer/stream, with workspace/subject authorization, and retain access to retired-field evidence. Add contact custom values to the payload without a new contact UI | Required for §9.6 evidence acceptance and §9.4 contact-payload promise; phase 5. Agree the small account evidence affordance with the redraw |
| D6 | Keep one aggregate invitation outcome card and the existing authenticated logo asset proxy; correct the design document to describe them | These existing differences were not covered by the two latest approvals; no new implementation needed if accepted |
| D7 | Use plain role text for non-managers if the spec's “hide management controls” rule is literal; retain a locked Admin control for owner rows viewed by managers | Resolves the remaining disabled-control presentation difference; small frontend correction after visual agreement |
| D8 | Retain current key-order platform listing, including bookkeeping keys | This is the written §9 default. Optional R-1 filtering is not a build blocker and must not become another visibility registry |

The Research fields table and Create form visual gate was satisfied on 2026-09-16 when the
founder approved the interactive preview. Phase 6 uses the existing Settings primitives with the
approved inline form and table layout. Backend-first scheduling no longer blocks this screen.

Pages decisions are listed in phase 8; the original spec does not define enough behavior to treat
its dummy controls as a ready API contract.

## 4. Phase 0 — establish the reviewed contract and baseline

- [ ] Record decisions D1–D8 and the design-gate scheduling decision in the design spec and the
  corresponding frontend contracts. Keep proposed choices marked proposed until approved.
- [x] Correct stale spec statements (“nothing implemented”, Settings returns 404), identify the
  implementation checkout, and preserve the original design pin/history (planning checkpoint).
- [ ] Capture current branch/head, one Alembic head and tracked diff before implementing. Preserve
  the rebased Settings changes and the backup branch; no additional rebase or remote push is needed.
- [ ] Retain separate checklist columns for code complete, automated checks, live proof and release
  deployment. No passing build or fixture screenshot can close the live columns.
- [x] Identify the actual source checkout for design commit `64232a0` before parity captures.
  Verified in `/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain`; the source
  still has the old Data model screen. No Research fields redraw was found there.
  Do not assume the historical `live-backend-v1` path or an arbitrary server on port 3000 is it.

**Exit:** approved delta ledger and a reviewable implementation sequence; no missing feature is
classified as complete merely because its dummy screen renders.

## 5. Phase 1 — close Profile/Workspace authority gaps

**Files:** auth `policy.py`; Settings API; frontend session permission schema/consumers;
Settings route; project accounts route and profile adapter; matching auth/frontend tests.

- [x] Introduce `workspace.manage_settings`, increment policy revision 2 → 3, grant it to owner
  and admin. Preserve `workspace.manage_members` for membership actions.
- [x] Replace the Settings helper's boolean `manage` switch with an explicit required permission.
  Recheck current membership and that permission inside the write transaction; retain workspace
  serialization and owner/self protections for member management.
- [x] Bind workspace rename and Research fields API authorization to the new permission; avoid stale
  permission literals in frontend validation or UI capabilities.
- [x] Make `/api/projects/[projectId]/accounts` resolve the same authenticated Settings profile
  as the protected layout. Reuse one mapping to `WorkspaceProfile`; retain fixture behavior only
  in the intentional accounts fixture path. Preserve authentication redirects and typed failures.
- [x] Search all remaining live `getWorkspaceProfile` consumers so a nested provider cannot
  restore the user-ID placeholder after profile edits.
- [x] Apply D7's agreed read-only member presentation. Keep suspended rows and retry behavior as-is.

**Verification:** owner/admin allowed, operator/viewer denied for workspace changes, own-profile
edits still allowed to active members, stale membership rejected. Profile display-name change
appears in the sidebar, global accounts and project accounts after refresh; clearing it falls
back to full name. Existing Members lifecycle tests remain green.

**Checkpoint:** one local commit for authority/profile coherence and its contract changes.

## 6. Phase 2 — implement the workspace research registry

**Files:** a new Alembic-generated revision off the then-current single head; registry module and
public exports; `tests/claimstore/test_field_registry.py` and focused workspace-registry DB tests.

- [x] Widen namespace/role/pack CHECKs precisely, add nullable `label`, allow null proposal ID,
  and **drop `pack` NOT NULL**. Preserve constraints on existing Client-KB rows and the proposal FK.
  Research rows must pair `account.*`/`contact.*` with the matching field class, null pack and
  `client_kb_role='research'`; do not permit arbitrary combinations through a broad OR.
- [x] Replace only the definition-table UPDATE trigger with the D1 guard. Permit label/description
  changes plus `definition_version = OLD.definition_version + 1` for research rows; reject edits
  to key, owner, schema, scopes, promotion/creation metadata and all Client-KB definitions.
  Leave retirement/materialization/readiness append-only triggers intact.
- [x] Extend the resolved registry metadata with label, presentation and creation time as needed.
  Reuse `promoted_by`/`promoted_at` for creator/time; avoid a second competing definition table.
- [x] Implement `register_workspace_research_field` with the exact §9.4 forced shape: JSON value,
  no schema constraint, deep pass, tenant-private, project-neutral, product forbidden, human
  creator, settings-v1 policy and text presentation. Keep `register_workspace_field` unchanged
  for its existing Client-KB callers.
- [x] Derive the key once in the registry. Trim/validate label and required description, preserve
  the immutable derived key after a label edit, and return actionable collision errors. Define a
  shared label limit (recommended 200 characters, matching other Settings names) in the contract.
- [x] Check global collisions and same-workspace collisions including retired keys. Preserve the
  ability for two workspaces to independently own the same private key.
- [x] Implement update with partial-field semantics and a row lock. Disjoint label/description
  patches must not overwrite one another; concurrent changes to the same property use the last
  committed patch. No-op requests must not manufacture version changes.
- [x] Keep retirement append-only with `human:<user_id>` and reason `settings`. Serialize edit,
  retire and claim validation/insert so the post-retirement guarantee is transactional.
- [x] Reuse erasure refusal; test create, edit, retire, list and claim writes for erased scope.
- [x] Document rollback: old schema cannot represent populated research definitions. Downgrade
  must refuse with an actionable message if such rows exist, rather than erase user data. Restore
  original constraints/trigger on an empty research slice; prove clean-DB up/down/up.

**Verification:** trigger-level tests as well as helpers; account/contact creation, invalid/blank
labels, whitespace-only descriptions, 2000-character bound, global/retired collisions, exact
version changes, immutable fields, two-workspace isolation and Client-KB regressions. Test races
using separate DB connections. Alembic must retain one head and both rebased migration histories.

**Checkpoint:** registry + migration + tests, with no new endpoint advertised yet.

## 7. Phase 3 — make research consume the registry safely

**Files:** `account_research_store.py`, `account_research_driver.py`, `account_research_launch.py`,
`claim_writer.py`, registry write gates; existing catalog/driver/launch/tools/writer tests.

- [x] Require a trusted `workspace_id` in both catalog readers. Merge global vocabulary with
  active, unretired, non-erased research definitions from only that workspace using the registry
  seam. Keep account `core.*`/`account.*`, person `contact.*`/`core.work_email`, facet grouping,
  schemas and contact use-class hints intact.
- [x] Update all three production call sites and test doubles. The Settings listing and research
  readers must use the same selection semantics; avoid independently maintained field menus.
- [x] Verify key and description reach both the acquisition context and structuring prompt.
  Preserve existing context construction and model configuration; no new agent, model or prompt
  version is needed solely to supply dynamic registry data.
- [x] Introduce a lifecycle refusal distinct from `UnknownFieldError` before fallback to a global
  row. Retired or erased local definitions cannot be resurrected by `_register_proposed_field`.
- [x] Apply D2 collision protection to global proposal registration too. Coordinate global and
  workspace registration for the same key; do not expose another workspace's label/description
  in a collision error. Test both orderings and simultaneous registration.
- [x] Hold the agreed field lock through validation and claim insertion; retirement takes the
  conflicting lock. A pre-retirement write may commit first; a write after retirement commits
  must refuse. Cover `validate_field=False` in the lenient writer rather than assuming the final
  insert repeats the registry gate.
- [x] Preserve the existing per-draft `write_each` failure receipts and successful sibling claims.
  Keep fetched artifacts under existing retention policy; a lifecycle refusal must not pretend
  the custom claim was stored. Exercise deterministic batch callers for unintended regressions.
- [x] Keep broad conversion of all agent-invented global proposals to workspace proposals as a
  separately reviewed Track R change. The narrow lifecycle/collision fix above is required here.

**Verification:** two workspaces with the same key/different instructions; a third workspace sees
neither. Exercise account, queued person and direct person launch. Inspect composed contexts;
write a real scoped claim in a DB test; assert no global row was created. Edit between compositions
and retire while a stale catalog remains in memory; confirm no resurrection or cross-tenant leak.

**Checkpoint:** catalog and claim lifecycle integration, proven independently of the UI.

## 8. Phase 4 — expose the Research fields Settings API

**Files:** Settings router, optionally a focused sibling module `research_fields.py` to keep
membership logic small; registry exports; `tests/auth/test_settings_integration.py` plus a focused
Research fields API suite; frontend Settings contract.

- [x] Implement the four specified routes: GET list by entity, POST create, PATCH label/description,
  DELETE retire. Active members may read; owner/admin with `workspace.manage_settings` may write.
- [x] Derive workspace and creator from the principal, never from request JSON. Recheck authority
  in the transaction. Map platform writes to `409 PLATFORM_FIELD`, collisions to `409 KEY_TAKEN`
  and invalid labels to `400 LABEL_INVALID`; specify missing/retired-row and invalid-body envelopes.
- [x] Return the specified bare row/list objects. Derive platform labels with the existing account
  label overrides; return registry descriptions verbatim. Sort platform rows by key, then workspace
  rows by creation time with a key tie-breaker. Resolve creator display name safely; erased/missing
  users must not break the list or expose their email.
- [x] Reuse existing request IDs, BFF routing, error envelope and disabled-feature behavior.
  Add no separate auth scheme, fixture fallback or visibility flag.
- [x] Prove extra-field rejection, entity filtering, four-role authority, workspace isolation and
  post-retire responses through ASGI. Inject membership revocation after principal resolution
  and verify POST/PATCH/DELETE all refuse inside the write transaction.

**Checkpoint:** reviewed API contract and working backend endpoints; frontend still honestly dummy
until phase 6 switches it over.

## 9. Phase 5 — connect results and evidence to the existing app

**Files:** `frontend_read/{v1_shared,contract_v1,account_detail,contacts}.py`; account/contact Zod
models and parity tests; account column/evidence consumers where the approved contract requires it.

- [x] Expand `_CUSTOM_FIELDS_SQL` per D4, retaining workspace, erasure, active and retirement
  filtering, subject scoping, supersession handling and newest-claim selection. Use `label` for
  research fields with a key-derived fallback; preserve legacy Client-KB label behavior.
- [x] Keep empty definitions out of account columns until a claim exists, as the current read
  contract does. Keep existing variable-column ordering/visibility state compatible.
- [x] Extend the custom-field result with the selected claim reference under D5. Reuse existing
  evidence types rather than duplicating source metadata on every column.
- [x] Make the detail evidence set and evidence-stream authorization use one consistent scoped
  rule that includes relevant custom-field claims. A generated page need not cite a claim to
  make that field's evidence accessible. Enforce subject/workspace ownership and existing privacy
  policy; evidence reads must not trigger generation or paid work.
- [x] Ensure retirement removes active field values/columns but retains an authorized way to read
  the historical evidence. Include retired declarations when resolving historical metadata;
  do not bypass erasure or return another entity's claims.
- [x] Define and serve contact custom research values and claim references in the contact detail
  payload. Preserve contact-use policy. Do not add a new contact UI slot without a design.
- [x] Update frontend parsing and backend/Zod parity together. Reuse the existing drawer for the
  agreed account affordance; test a custom field omitted from the generated overview, including
  its retired state, so evidence access is deterministic rather than dependent on model choices.

**Verification:** list and detail show the same label/value; long labels remain usable; no empty
column appears; retirement removes the column; old evidence remains accessible; contact values
are present in the payload; cross-workspace/cross-subject/erased evidence requests refuse.

**Checkpoint:** an API-created field can travel through catalog → claim → app read → evidence.

## 10. Phase 6 — replace Data model with Research fields

**Design gate satisfied, 2026-09-16:** founder approved the interactive Research fields preview
and reuse of the existing Settings primitives. The screen now follows that preview.
Before writing Next.js code, read the installed Next guides required by `apps/frontend/AGENTS.md`.

**Files:** `features/settings/components/data-model-settings.tsx`, navigation, route model and
catch-all loader; new `model/research-fields.ts`, `data/research-fields.repository.ts`, focused
state hook; existing `settings.actions.ts`, primitives, confirmation card and CSS tokens.

- [x] Keep the Accounts/Contacts overview; replace fixture rows with server-loaded, Zod-validated
  rows. Rename the page/navigation to Research fields per the redraw.
- [x] Remove Type/Editable by/AI fill, Relationships/Display and Restore defaults from this live
  surface. Remove unused fixture logic rather than leave a second seemingly functional editor.
- [x] Preserve `/settings/data-model/{accounts,contacts}` and existing `/fields` links. Recommended
  compatibility behavior for old `/display` links: redirect to that entity's field list; record
  it in the route contract. Invalid entities/nesting still return 404.
- [x] Render Name, Description, origin/creator/time and permitted row actions. Platform rows have
  no edit menu. Non-managers have neither Create nor row actions.
- [x] Implement Create with required Name/Description and inline KEY_TAKEN error. Prevent duplicate
  submissions; add the returned row in creation order; show “Field created”.
- [x] Reuse autosave for label/description; multiline descriptions save on blur or Cmd/Ctrl+Enter,
  Escape restores. Handle focus order, pending state, failure rollback, scope changes and two
  independent edits without stale response overwrites. Show “Field updated”.
- [x] Implement in-place Retire → Confirm retire; no modal. Explain irreversibility/key reservation,
  remove the row only on success and show “Field retired”.
- [x] Preserve typed recovery, no fixture fallback, token-based styling and accepted confirmation
  behavior. Recheck the Members long-email layout at the same time as the final Settings walk.

**Verification:** schema/action/hook tests for errors, autosave/revert and stale scope; browser walk
of create/edit/retire/reload and non-manager view. Use ChatGPT browser control as requested. Compare
desktop and narrow viewports against the approved frames; no table-cell overlap or focus traps.

**Checkpoint:** Research fields UI integrated, not yet declared live-accepted until phase 7.

## 11. Phase 7 — run real acceptance and close the original integration

### Runtime preparation

- [ ] Recheck runtime ownership and versions before touching processes. The last recorded isolated
  Irvine stack is frontend **3147**, API **8170**, design **8171**, Redis **6471**, database
  **clue_irvine_settings_live_20260915** on localhost **55040**. Its last verified DB revision was
  **27aa2ae947bc**; the rebased code head is **6d25b68bff68** before the future research migration.
  These are prior observations, not fresh service-health claims from this planning session.
- [ ] Inspect ignored runtime overrides rather than assuming root `.env` selects this stack.
  Back up the intended DB, migrate it to the then-current head, rebuild/restart only its services
  and restart its three workers after checking active jobs. Do not interrupt another worktree or
  reset the existing live DB. Verify each process runs the intended checkout and configuration.
- [ ] Check Clerk secret presence and origin without printing secrets. They were configured in
  the earlier Irvine run; do not ask for replacement credentials without checking. Recheck paid
  provider readiness only for the chosen research flow; the earlier onboarding run hit Exa
  `payment_required`, so worker health alone is insufficient proof of research readiness.

### Profile, workspace and members

- [ ] Sign in as owner/admin through the browser, edit/reload profile and workspace name, and verify
  browser → API → DB results. Restore temporary test names and check project accounts too.
- [x] Send one invitation to the already-authorized test recipient through Members. Avoid a
  separate provider user-lookup prerequisite. Keep the address in the session/application, not
  committed test fixtures or this document.
- [x] Record the backend outcome honestly: provider acceptance is not inbox delivery. If the
  address already belongs to a Clerk user and returns `created_no_email`, that validates only
  the existing-user path; a genuinely new address is needed to prove the email path.
- [x] Have the recipient open the email and complete signup/acceptance. A localhost redirect must
  be opened on the machine running the app; for another device use an agreed reachable test
  origin. The user confirmed receipt and successful acceptance on 2026-09-16 after the required
  password fix; a fresh Members page shows the joined Member and today's joined date.
- [ ] Independently verify the invitee's selected workspace and destination after acceptance in
  their signed-in session. The inviting administrator's Members page does not establish this.
- [ ] Walk role change, removal, blocked access, re-admission and revocation using the test member.
  Preserve owner/self guards. Observe failed-delivery guidance without adding resend behavior.
- [ ] Cover expiry, wrong verified address, revoked token, replay, stale actor and provider failure
  deterministically in integration tests; do not manufacture those failures against a real inbox.

### Research fields

- [ ] Create the specified account field with a real instruction in the UI, reload to prove DB
  persistence, and start one bounded research job on an agreed existing account. Record the
  workspace/run/job/field/claim IDs and evidence references, without sensitive source excerpts.
- [ ] Confirm the instruction exists in the composed context, the resulting claim is private,
  the column displays the value and its evidence opens. No manually inserted claim qualifies as
  this live proof. A legitimate “not found” is an honest run result, but does not by itself prove
  the successful-value path; choose suitable source-backed test material for that proof.
- [ ] Edit the instruction and verify a newly composed job uses the update. Retire the field,
  reload, verify it leaves the catalog/column and its prior evidence remains readable.
- [ ] Verify the contact path too: created contact field reaches person research and the detail
  payload; no invented contact UI is required. Confirm account/person direct-launch coverage.
- [ ] Check operator/viewer read-only behavior and cross-workspace isolation with controlled test
  identities. Do not send additional invitations without the corresponding authorization.

**Exit:** evidence ledger names each tested path and unresolved failure. “Code implemented” is
permitted before this phase; “live integration complete” is not. The intended release deployment
must be explicitly identified; the old spec's san-salvador acceptance target is not permission to
operate a sibling stack. Pages V1 completion remains phase 8, not an implied result of this phase.

## 12. Phase 8 — implement Pages Settings for V1

This work is required, but the accepted product scope is narrower than the dummy form. Reuse the
existing design publisher and its package/revision/rollback path.

### Contract review before coding

- [ ] Define the defaults' owner: recommended workspace-scoped Settings, resolving the approved
  brand kit through an existing platform/design seam, without imports across subsystem internals.
- [ ] Define metadata precedence: recommended explicit document metadata first, then approved
  brand-kit defaults, then the publisher's current safe title/description/image fallbacks. Confirm
  whether Settings exposes these brand-derived values read-only or permits workspace overrides.
- [ ] Define when a changed default affects output: recommended on next publish; no silent
  republish of every existing page. Pin resolved values into immutable publish revisions so a
  rollback restores the actual previously published package.
- [ ] Define fallback URL behavior for missing, withdrawn and invalid slugs, including loop
  prevention and workspace isolation. Do not turn every error into a redirect by default.
- [ ] Specify allowed head/body snippet capabilities and validation, who may manage them, and how
  scripts are isolated from the authenticated application. The original spec explicitly requires
  a security review here. Do not persist arbitrary executable markup before that contract exists.
- [ ] Confirm the reduced V1 form: remove custom domains, uploads, indexing/follow toggles and
  llms.txt controls from the operational screen. Preserve ABM noindex; the current dummy remains
  visible until this reduced form is approved and bound.

### Implementation sequence after review

- [ ] Add the minimal workspace-settings persistence through the owning subsystem, with one
  reversible migration and owner/admin authorization; do not create a second brand-kit store.
- [ ] Define GET/PATCH Pages Settings schemas and error behavior at the frontend repository seam.
  Validate URLs, partial updates and the approved snippet policy on the server.
- [ ] Pass the resolved defaults through the existing `publish_web_document` →
  `build_publish_package` path. Cover every publish entry point, including ABM batch and republish;
  retain the existing noindex and revision-digest invariants.
- [ ] Bind the approved Pages form with the same autosave/recovery/confirmation behavior. Avoid
  adding Settings-only browser fetches inside presentation components.
- [ ] Verify workspace isolation, metadata precedence, public assets, fallback behavior, snippet
  refusal cases, immutable published output, rollback, and ABM noindex. Use a controlled test page
  before publishing real customer-facing assets.

**V1 exit:** save → reload → publish → inspect actual served HTML/assets → revise → republish →
rollback has evidence. A screenshot of the dummy form cannot satisfy it. Its contract/frames are
an explicit remaining dependency, not a reason to claim the release feature is complete.

## 13. Verification gates and implementation checkpoints

Run meaningful tests per phase, then the combined affected suites once integration is complete.
Do not rerun paid jobs or destructive migration smoke against live state as a generic check.

| Gate | Required evidence |
| --- | --- |
| Migration | One Alembic head; up/down/up on a named disposable DB; populated-downgrade refusal; unchanged legacy Client-KB rows |
| Registry | `tests/claimstore/test_field_registry.py` plus scope/lifecycle/concurrency tests and existing Client-KB/erasure coverage |
| Research | `tests/arv2/test_claim_writer.py`, catalog/store/driver/launch/tools suites, including real DB variants |
| API/auth | `tests/auth`, focused Research fields endpoints; member/profile/workspace regressions |
| Projections | `tests/api/test_frontend_read_{v1_shared,accounts_list,account_detail,contacts}.py`, schema parity and evidence authorization |
| Frontend | `npm run design-system:build`, `npm run lint`, `npm test`, `npm run build` in `apps/frontend`; repository-required checks for changed Python and dependency seams |
| Visual | ChatGPT browser screenshots at matching viewports against the pin/approved redraw; keyboard and narrow-width checks |
| Live | Real invitation receive/accept and real account/person research receipts, tied to the exact runtime and DB revision |
| Pages | Existing design publisher tests plus new defaults/snippet/fallback tests and actual published HTML inspection |

Use an explicit disposable `CLUE_DATABASE_URL` for `make db-smoke` and DB tests after verifying the
test harness's DSN handling. Never run smoke with a DSN inherited from an uninspected env file.
For design changes, read `subsystems/clue-design/AGENTS.md` and use its toolchain/test gate first.
New env settings, if any become necessary, must land with `.env.example` parity; none are needed
merely to enable the Research fields API beyond the existing Settings/frontend-read configuration.

Suggested local commits follow phases 1, 2, 3, 4, 5, 6, acceptance fixes, and coherent Pages slices.
Each includes matching contracts/tests. Do not publish or force-push rewritten history as part of
this plan without an explicit push instruction.

## 14. Dependencies, remaining follow-ups and honest completion

**From the founder/co-founder:** settle Pages defaults/fallback/snippet behavior and approve the
pending permanent retirement of the disposable browser-test field. Research fields visual approval
and the recipient's invitation acceptance are complete. No replacement backend or Clerk credentials
are known to be required.

**From the implementation:** complete the remaining phase 7 live research and membership lifecycle
checks, observe the invitee's selected workspace, and build phase 8 for V1 after its contract review.
Research fields management is implemented and automated checks pass; generation into a sourced
account column is still a separate live test. Existing provider access may need resolution for that
case; verify the actual failure first.

**Explicit follow-ups outside this completion slice:** broad workspace-local agent proposal
registration (Track R) now has a founder-requested
[implementation plan](2026-09-16-workspace-agent-proposed-fields.md), prepared 2026-09-16;
implementation/resource activation remain open. Other follow-ups: contact custom-field
presentation frames, usage-only Billing with real
plan/credit data, connections/MCP/integrations, website/rebuild flow, avatar upload and viewer-role
UI. These stay visible in the ledger; none may be described as implemented by this work.

**Verification baseline from the preceding rebase session:** 131 focused backend tests, 9 focused
frontend tests, design-system generation/lint/build, 27 dependency contracts, and disposable-DB
migration smoke passed. This planning session did not rerun those checks, send email, execute
research, migrate the live DB or verify a deployment. Those results cover the existing integration
only, not the unchecked phases in this plan.

Close the task only with a final matrix that states, per feature: implementation commit, automated
test evidence, live acceptance evidence, deployment target/revision, and any remaining dependency.
The phrase “Settings complete” is not justified while required Research fields or Pages V1 work,
or the relevant live acceptance, remains open.
