# Projects, threads, generations, and artifacts API contract

Status: **R0 ratified; repair slices R1-R9 implemented; Stage-0/project hardening contract ratified and Slices 0-4 implemented. Slice 5 is explicitly deferred. Slice 6 automated/adversarial acceptance is complete, but authenticated browser acceptance remains pending. The combined human-gate contract is ratified; its merge implementation and acceptance remain pending. Later slices remain pending where noted.**

Owner for backend integration: Aaryan.

## Automatic ICP and product targeting — founder ruling 2026-09-21

This amendment supersedes the human-approval requirement for ICP and product
selection in the historical sections below. New project turns use
`head-of-abm@v61`, `stage0-interview@v35` and `configure_project_targeting@1`.
The agent reads the current ICP, applies its product set (or the user's requested
override), confirms the exact artifact and pins it to the project without opening
an approval card. Existing project overrides survive repeated application of the
same ICP. The tool returns the artifact digest and product-selection version so
the requested task can continue in the same turn.

The backend records an automatic initiating-turn reference, never a fabricated
human gate answer. Product selection remains versioned and scoped to active
products from this project's brand. Historical human gates and receipts remain
readable; account selection, spending and other human decisions retain their
existing contracts. No frontend payload changes or client-side auto-answering
are introduced.

## Canonical frontend routes — founder-ratified 2026-08-17 (Phase R, rulings R1–R3)

Adopted from the design repo's canonical-routes contract
(`clue-hq/clue-frontend` `docs/api-contracts/projects.md`), as built by the
Phase R route migration (`docs/superpowers/plans/2026-08-17-phase-r-chat-route-migration.md`):

| Destination | Route | Ownership |
| --- | --- | --- |
| Projects list | `/projects` | Workspace |
| Project root | `/projects/:projectId` | Legacy absorber: `?thread=` server-redirects to the chats path; threadless renders and canonicalizes to the default thread's chats path |
| Project Gallery | `/projects/:projectId/chats/:chatId?surface=gallery` | One Gallery per Project |
| Legacy Gallery entry | `/projects/:projectId/gallery` | Compatibility redirect only; threadless carries `?surface=gallery` through the absorber so the Gallery intent survives |
| Project chat | `/projects/:projectId/chats/:chatId` | Many chats per Project; the canonical thread `href` shape every backend emitter produces (`thread_href` in `platform/api/clue_api/chat/schemas.py`) |
| Project artifact | `/projects/:projectId/artifacts/:artifactId` | Artifact remains in the Project Gallery |

**The legacy `/projects/:projectId?thread=:chatId` form redirects to these
canonical destinations and must not be emitted by new UI or by the backend.**
Pane state on the chats route is `?surface=` (`chat|gallery|web|ad`) plus
`?edit=1` and `?selection=` — **this supersedes the earlier-ratified
`?artifact=` split-view param (ruling R2, 2026-08-17), which was never built
and must not be introduced.** The historical-proposal sections later in this
document retain the legacy `?thread=` form as unedited history and are
non-authoritative. The R6 protected-shell paragraph ("R6 implementation
status") is unchanged by the route migration.

**Chat-flow editor integration — as built, 2026-08-19** (plan
`docs/superpowers/plans/2026-08-19-chat-flow-editor-integration.md`, slices 1–5,
commits `f7540b63`/`f6d63cdc`/`3957166a`/`3ba169be`/`95922696`):

- **The chats-route feed props.** `chats/[chatId]/page.tsx` server-fetches the
  per-project design-artifact feed (`loadGalleryFeed` — the same shared helper
  the artifact page uses) and threads `{artifacts, documentIds}` as NEW
  optional props through `ProjectWorkspaceShell` → `ChatSurface`. The feed
  rides these props only; `workspace.artifacts` remains the schema-hard empty
  tuple (`z.tuple([])`) and is NOT the artifact transport. Absent props (the
  legacy `/projects/:projectId` absorber) → the gallery keeps its honest empty
  state.
- **Pane-state write-back.** The R2 params now round-trip: the chats route
  reads them once at mount (unchanged) and writes them back on every pane
  change via `router.replace` (never `push`; loop-guarded; params it does not
  own — `?handoff=`, anything future — survive). Serialization rules: resting
  state (rail closed) = the bare URL with NO pane params; `?surface=chat` is
  its accepted inbound alias (parsed deliberately, canonicalized back to the
  bare URL); `surface=web|ad` from the open artifact's kind; `edit=1` only on
  the artifact surface while editing; `selection=<inspector schema token>` only
  while editing and only when ≠ `canvas`. `?artifact=` is never emitted
  (test-pinned).
- **Known limitation — deep links restore pane state, not the open artifact.**
  The ratified vocabulary carries no artifact identity (artifact identity on
  the chats route is a runtime tab selection, not a URL param), so a shared
  `?surface=web&edit=1&selection=text` URL opened fresh lands rail-open on the
  Gallery with the conversation showing; the pane params survive un-rewritten.
  **Open founder decision (surfaced 2026-08-19, undecided):** whether to ratify
  an artifact-identity param so a shared link reopens the exact artifact in the
  exact editing state — any such param needs a new ruling since `?artifact=`
  is superseded and forbidden.

The durable thread/turn/gate/stream surface, atomic Home bootstrap, complete
project workspace read, and tenant-scoped sidebar catalog are implemented.
In HTTP mode those repositories all use authenticated backend data and never
fall back to fixtures. ~~Artifact integration is not yet available, so a real
project deliberately returns and renders an empty Gallery.~~ **[Superseded
2026-08-18/19: the leg-derived per-project design-artifact list read is live
(`GET /api/v1/projects/{id}/design-artifacts`), and both the artifact route and
the chats route serve the real gallery feed through it — see the chat-flow
section above.]**

Authority order inside this document is:

1. **Combined human-gate amendment (2026-08-15)** below.
2. **Stage-0/project hardening amendment (2026-08-11)** where the combined amendment does not supersede it.
3. **Executable integration contract (2026-08-10)** where neither amendment supersedes it.
4. **As-built thread-shell contract (2026-08-08)** for endpoints the executable
   section does not amend.
5. Earlier read/write/preview proposals, retained only as design history.

When `CLUE_PROJECTS_API_BASE_URL` is configured, every projects repository must
use the same-origin authenticated BFF and validate the corresponding wire
schema. HTTP mode never falls back to fixtures after a refusal, parse error, or
network failure. Presentation components do not call the API directly.

### Product-set selection — as built (2026-09-09, O6)

The pointer below is now implemented in the frontend model and card. What the client actually
speaks:

- **New gate kind `product_set_selection`.** It joins `directive_confirmation`,
  `icp_confirmation` and `product_selection` in `SUPPORTED_GATE_KINDS`; its title is "Choose this
  project's products". An unsupported kind still renders the existing "not available here yet"
  notice, so an unknown kind can never be answered.
- **Snapshot members the card reads** (`subject_snapshot`): `brand_id`, `catalog_document_id`
  (nullable), `catalog_version`, `products[]`, `omitted_count`, `current_selection`
  (`{selection_version, product_ids}` or null) and `suggested_product_ids[]`. Each product carries
  `product_id`, `name`, `short_description` (`""` when the catalog does not describe it),
  `aliases[]`, `status`, plus the nullable `resolution_state`, `reconcile_confidence`,
  `reconcile_reason`, `offering_kind`, `family`, `lifecycle` and `official_url`. The boxes are
  pre-checked from `current_selection.product_ids` when the project already has a set, else from
  `suggested_product_ids`; an `archived` product is never pre-checked and cannot be checked.
- **Answer transport.** The turn body's `gate_response` carries `selected_product_ids: string[]`
  (≥ 1, unique, each a non-archived product of the immutable snapshot) and only with
  `decision: "approved"`. It is mutually exclusive with `revision_request` and with the historical
  `selected_product_id`. The backend refuses `revision_request` on this kind (422
  `GATE_REVISION_REQUEST_UNEXPECTED`) and refuses `selected_product_id` (422), so the card offers
  no revision textarea for it. The durable answer records
  `decision_payload.selected_option_refs[]` with `selected_option_ref: null`, and the answered
  card reads its receipt from there.
- **The subject ref** is D10's `brand-product-catalog:{brand_id}:{catalog_document_id or 'none'}`
  with the catalog document's version (or 1) as the revision — no Client-KB version appears in it.
- **The `@2` ICP gate is unchanged for the client.** Its kind is still `icp_confirmation` and its
  `subject_snapshot` still carries `icp_key`, so the existing ICP card, its revision textarea and
  its summary render it without a single frontend change; what moved is the backend's subject —
  `subject_kind: "brand_knowledge_document"`, the ICP knowledge document rather than the old
  Stage-0 spec row.

Full wire shapes and rendering rules: `docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` §6.3, §7.

### Product-set selection amendment (2026-09-07) — pointer

Founder ruling P1 (Aryan, 2026-09-07): **a project targets a set of products, not one.** For new
projects the `product_selection` kind below is replaced by `product_set_selection`, whose approved
answer carries `decision_payload.selected_option_refs[]` (≥ 1, each a candidate in the immutable
snapshot) and whose browser transport member is `selected_product_ids[]`. The snapshot gains
`offering_kind`, `family`, `lifecycle`, `official_url` per product and a `current_selection`
member; the card renders checkboxes grouped by offering kind and "Use these products". The set is
re-selectable at any time as a new `selection_version`; runs keep the version they pinned. The
single-product contract below stays for replay of historical gates only. A candidate whose
onboarding lineage row is `model_unsure` — the catalog identity ladder minted it rather than
merging it onto an existing product, at less than high confidence — is **flagged for the gate**,
so the human decides whether it is really a distinct offering (how the flag renders is O6's, not
this pointer's). Wire shapes, rendering rules, and the durable `project_product` table:
`docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` §5.1, §6–§7. This amendment is a pointer; the
Zod/schema changes land with that contract's charter.

### Combined human-gate amendment (2026-08-15)

This amendment freezes the merge contract shared by directive confirmation,
ICP confirmation, and product selection. It defines the target shape before the
schema, backend, resource, frontend, and test conflicts are resolved; it is not
an assertion that the combined implementation has already passed acceptance.

#### One durable gate substrate

- The current interactive gate kinds are `directive_confirmation`,
  `icp_confirmation`, and `product_selection`. `plan_approval` and
  `budget_approval` remain reserved gate vocabulary, but do not become
  interactive merely because their strings are recognized by storage.
- Every immutable gate retains its exact workspace, project, thread, opening
  turn, kind, subject reference, nullable subject revision, canonical subject
  snapshot, matching SHA-256 digest, permitted decisions, human addressee, and
  privacy/erasure bindings. The model may ask to open a gate; it cannot author
  any of that authority.
- `max_spend_cents` and `currency` are a paired nullable value. Non-spend gates
  store both as null. When an amount is withheld by deployment policy, every
  human-visible projection also returns null/absent rather than manufacturing
  `0`, an empty string, or an empty currency.
- Erased snapshots, stale subjects, foreign workspace/project/thread gates,
  wrong addressees, malformed references or digests, unsupported kinds, and
  already-answered gates are non-interactive. The frontend renders recovery,
  never decision controls, for those states.

Every immutable answer receipt retains the answering turn and action reference,
decision, reviewed subject digest, `decision_payload`, nullable
`selected_option_ref`, human actor, and answer time. The route derives actor,
action, scope, and durable option reference; none is accepted as browser or
model authority.

#### Kind-specific answer invariants

| Gate kind and decision | Required auxiliary value | Forbidden value |
|---|---|---|
| `icp_confirmation + revised` | one bounded, trimmed, non-blank `decision_payload.revision_request` | `selected_option_ref` |
| `icp_confirmation + approved/rejected` | empty `decision_payload` | `selected_option_ref` |
| `product_selection + approved` | one `selected_option_ref` proved to be a candidate in the immutable snapshot | any `decision_payload` member |
| `product_selection + rejected/revised` | none | `selected_option_ref` and every `decision_payload` member |
| `directive_confirmation` | none under the current contract | `selected_option_ref` and every `decision_payload` member |

`decision_payload` is reserved for bounded auxiliary decision input; its only
current member is the ICP `revision_request`. `selected_option_ref` is the
dedicated durable product-selection field. A request or receipt can therefore
never carry both revision text and a product choice. Every decision must also
belong to the exact gate's `permitted_decisions` tuple.

#### Frontend request and presentation contract

The turn endpoint retains one structured `gate_response` alternative to a
normal message:

```jsonc
{
  "gate_id": "<durable-gate-uuid>",
  "decision": "approved|rejected|revised",
  "expected_subject_sha256": "<64-lowercase-hex>",
  "expected_estimated_cost_cents": null,
  "revision_request": "<ICP revision text; only when required>",
  "selected_product_id": "<catalog product id; only when required>"
}
```

The last two members are mutually exclusive and are omitted unless their gate
kind and decision require them. `selected_product_id` is a browser transport
name, not durable authority: after validating membership in the gated snapshot,
the server persists the corresponding value as `selected_option_ref` and
invokes the existing human-only product confirmation operation.

Frontend decision state is a discriminated union keyed by gate kind and action:
an ordinary decision, an ICP revision with required text, or a product approval
with one required candidate. It must not overload a generic third string as
either revision text or product ID. The card dispatches by fetched durable
`gate.kind`; unsupported or invalid shapes fail closed.

Canonical answer history renders semantic receipts. Product approval shows the
chosen product's retained display name from the immutable gate snapshot, never
raw transport JSON or a technical product ID. ICP answers retain the existing
Profile approved/declined/Changes requested presentation. Optional members that
were absent from a historical canonical message remain absent during replay.

### Ratified Stage-0/project hardening amendment (2026-08-11)

This amendment replaces the browser-probe defects documented in
`.context/defect-log.md` with one durable authority chain. Slice 0 freezes the
contracts and repairs the two stale test signals. Slice 1 registers the trusted
readiness and synthesis tools, persists their durable records, and promotes the
active Stage-0 recipe/profile. Slice 2 implements the durable ICP gate and
answer lifecycle; rendering and remaining UI changes stay owned by Slices 3-6.

- `synthesize_icps` is available to the governed Stage-0 conversation profile.
  A successful call persists one or more draft, versioned `icp_spec` rows and
  returns their exact durable proposal references. A readiness-policy revision
  is never described or serialized as an ICP version; no ICP exists until an
  `icp_spec` row exists.
- ICP confirmation is a supported durable `agent_gate` kind. Its immutable row
  stores the exact ICP subject reference, ICP revision, canonical subject
  snapshot SHA-256, permitted decisions, and human addressee. Only the stored
  gate may produce interactive Approve, Reject, or Revise controls.
- A gate response travels through the existing structured `gate_response`
  route. The server revalidates workspace/addressee, permitted decision,
  subject revision, and expected digest before inserting the immutable answer
  receipt. Approve activates the exact draft ICP; Reject and Revise preserve
  the receipt without activating it.
- Thin model references, malformed ids such as `human_only`, unsupported gate
  kinds, missing durable rows, and stale subjects render as non-interactive
  **Human action required** recovery notices. A model-emitted digest is not
  authority.
- Stage-0 readiness input metrics are engine-derived from the pinned,
  account-wide company Client-KB claims. The confirmed product is a separate
  trusted project pin, and its optional Product-KB has an independent version;
  company and product version numbers are never required to match. Coverage and
  verified-claim counts use the effective expected-field set: the substantive
  company Client-KB baseline plus any tenant-local required-field extensions.
  An empty configured extension list cannot erase the baseline or turn an empty
  knowledge base into a misleading ready state. The wire field is named
  `readiness_policy_version`.
- Home project creation accepts an optional explicit `project_name`. When it is
  absent, the server derives a bounded durable name from the initial brief.
  The same stored title feeds bootstrap, project header, and sidebar reads;
  `Untitled project` is no longer the creation default.
- The authenticated session membership includes `workspace_name`. Shell
  controls render that display name while retaining `workspace_id` only as the
  internal selection value.
- During text-only Stage 0 an empty Gallery is collapsed by default, with an
  explicit reopen control. Composer submission clears both browser-owned draft
  state and the focused Slate value; layout permits bounded editor scrolling
  without horizontal conversation overflow or sticky-header clipping.

#### Slice 4 presentation and workspace invariants

- A successful submission clears the exact accepted prompt and ordered mention
  set from both controlled draft state and Slate history. A newer draft typed
  while the request is in flight is not cleared, and blur is not a second
  draft-authority path.
- Canonical structured gate-response messages remain immutable in storage, but
  the default transcript projects the fetched durable answer as **Profile
  approved**, **Profile declined**, or **Changes requested**. The normal chat
  never renders the gate id, expected digest, subject id, or transport JSON;
  those details remain available through the developer inspector API. As of
  2026-09-20, chat no longer renders the Inspect action or drawer and does not
  probe inspector availability.
- As of 2026-09-20, the shared chat renderer also omits `tool` parts in every
  state. Per-call activity rows such as **Complete a project step** and **Save
  your answer** are absent across all conversations, including replayed history
  and live updates. Tool execution, event persistence and wire payloads are
  unchanged; reasoning, response text, research tasks, plans and approval cards
  retain their own presentation.
- The composer height is content-driven and bounded. The editor scrolls
  internally before it can overlap the mention/model/send footer.
- Every split-pane and transcript flex boundary may shrink (`min-width: 0`),
  message prose and inline code wrap, and only vertical conversation scrolling
  is permitted. New user turns are positioned below the project and thread
  headers rather than under them.
- A project with no artifacts opens conversation-first and exposes an obvious
  **Open Gallery** control. The explicit `/gallery` route still honors the
  user's request to open the Gallery, including its empty state — since
  Phase R it does so as a compatibility redirect carrying `?surface=gallery`
  through the absorber (see "Canonical frontend routes" above).

The amendment supersedes the earlier `Untitled project` and initially-open empty
Gallery rules retained later in this document as implementation history.

#### Slice 6 acceptance checkpoint (2026-08-12)

Slice 6 tests Slices 0-4 only. The workspace-display-name and durable-project-name
changes assigned to Slice 5 are deliberately excluded from both acceptance and
adversarial conclusions.

- A fresh isolated PostgreSQL database completed head → previous revision → head
  across the two Stage-0 migrations, and Alembic reported one head.
- The focused backend/adversarial matrix passes 165 tests. It includes the trusted
  readiness inputs, versioned ICP synthesis, exact-subject gate lifecycle, all
  three human decisions, replay/tenancy/digest refusals, durable-turn fixture,
  active skill materialization, the complete tool-authority registry, and the
  promoted-recipe lifecycle.
- Frontend acceptance passes 165 tests, ESLint, design-system token generation,
  and the Next.js webpack production build.
- The complete repository suite passes 4,381 tests and skips 23. Its remaining
  failures are classified separately: shared-database/order-sensitive legacy
  tests, the pre-existing clue-design logging-discipline scan, and an untouched
  mypy failure in `agent_gate_tools.py`. Slice-owned registry/recipe failures
  found by this run were repaired and pass in isolation and in the focused
  matrix.
- Authenticated browser acceptance remains open. The in-app Clerk session was
  expired; Chrome could enumerate tabs but could not establish a controllable
  acceptance tab even after the one supported recovery attempt. No fixture-only
  browser run is accepted as a substitute for browser → API → PostgreSQL proof.

#### Frozen Stage-0 authority contracts

The confirmed-discovery transition has an additional ratified amendment:
[`FI-stage0-confirmed-discovery-run-contract.md`](../../../../docs/specs/FI-stage0-confirmed-discovery-run-contract.md).
The frontend never submits a `product_context_version_id`, readiness decision id, ICP lineage,
Client/Product-KB version, or budget value to start the active confirmed run. The backend derives
or reuses the immutable context receipt from the already pinned Stage-0 inputs. With
`CLUE_BUDGET_CONTROLS_ENABLED=false`, no discovery-spend gate is returned or rendered; the
boundary is evaluated and recorded internally in record-only mode. Discovery count/criteria, when
they genuinely require confirmation, use the separate directive-confirmation flow and are not
product-context or budget authority.

The existing `evaluate_stage0_readiness@1` and `synthesize_icps@1` schemas remain
unchanged for historical replay. Their corrected successors are new versioned
contracts. Slice 1 registers their `@2` successors without silently changing an
`@1` schema already pinned by profiles and receipts.

`evaluate_stage0_readiness@2` exposes exactly one model-authored input:

```json
{ "gate": "icp_synthesis" }
```

Workspace, project, product, client entity, pinned Client-KB version, claim set,
field policy, metrics and verdict are trusted runtime/backend values. The model
cannot supply or override them. Its reference-first output is:

```json
{
  "readiness_decision_id": "<uuid>",
  "gate": "icp_synthesis",
  "verdict": "ready",
  "coverage_ratio": 0.78,
  "verified_claims": 0,
  "available_field_keys": ["client.differentiator", "client.product"],
  "reason_codes": [],
  "readiness_policy_version": 1
}
```

The Insight Health fixture currently has seven available baseline fields out of
nine, but those official-site claims are not independently verified; its
authoritative metrics are therefore `coverage_ratio=7/9`,
`available_field_keys` containing seven entries, and `verified_claims=0`.

`synthesize_icps@3` has no model-authored input fields. The runtime supplies the
exact ready Stage-0 scope and links the write to the readiness decision. It
returns one or more persisted draft references plus bounded, exact presentation
projections of those same drafts:

```json
{
  "readiness_decision_id": "<uuid>",
  "icp_specs": [
    {
      "workspace_id": "<internal-workspace-id>",
      "icp_key": "independent-neurosurgery-practices",
      "icp_version": 1,
      "status": "draft"
    }
  ],
  "presentations": [
    {
      "icp_key": "independent-neurosurgery-practices",
      "icp_version": 1,
      "name": "Independent neurosurgery practices",
      "rationale": "Practices where missed calls and manual routing constrain growth.",
      "target_criteria": ["Independent neurosurgery practice", "US-based"],
      "buying_signals": ["High inbound call volume", "Manual scheduling workflow"],
      "discovery_motion": "discovery",
      "content_truncated": false
    }
  ]
}
```

The agent writes this synthesis as the normal assistant message in the same
awaiting-input turn that opens the separate ICP approval card. The card is only
the decision control; it does not
replace, contain, or hide the explanatory ICP message. Opaque lineage fields are
not a substitute for the presentation.

An interactive ICP gate has kind `icp_confirmation` and stores the durable
`icp_spec` composite reference, the same ICP version as `subject_revision`, the
canonical subject snapshot, its matching SHA-256 digest, the exact permitted
decision tuple `approved | rejected | revised`, and `addressee_user_id`.
`human_only`, a model-produced digest, or an unfetched `open_gate_ref` cannot
satisfy this contract.

The normal turn route carries an ICP answer as
`gate_response={gate_id, decision, expected_subject_sha256,
expected_estimated_cost_cents:null}`. A `revised` decision additionally requires
one bounded, non-blank `revision_request`; that text is persisted in the answer
receipt and the gated draft remains byte-identical. Approve and Reject accept no
revision payload. The shared cost echo remains governed by the existing
directive/budget-gate rules when that gate stores a spend amount. Actor,
addressee, action reference, subject and authority remain server-derived and
are never accepted from the browser or model.

#### Slice 2 implementation status (2026-08-12)

- `open_icp_confirmation_gate@1` is registered in the promoted Stage-0 profile
  and recipe. The model supplies only a synthesized `icp_key` and version; the
  runtime derives the project, thread, exact draft snapshot/digest, supported
  decisions and human addressee.
- `agent_gate.permitted_decisions` is durable data. Non-spend gates store a
  paired null amount/currency rather than a fabricated zero. Each immutable
  answer receipt echoes the reviewed digest and stores a bounded structured
  decision payload.
- Route checks and a database trigger independently enforce the exact digest,
  permitted decision and addressee. The route also re-resolves the current
  product/client/Client-KB lineage and compares the complete draft snapshot
  before accepting a new answer.
- Approve activates exactly the gated draft in the same transaction as the
  receipt. Reject leaves it draft. Revise stores the requested changes and
  leaves the original draft unchanged so a later synthesis must create a new
  version.
- Slice 2 deliberately stopped at the backend authority boundary. Slice 3 now
  provides the typed ICP decision surface, including the required Revise input,
  without treating rich stream fields as authority.

#### Slice 3 implementation status (2026-08-12)

- A gate part is only a signal to resolve an `agent_gate` UUID. Decision controls
  are derived exclusively from the fetched durable gate after exact workspace,
  project, thread, subject revision/digest, supported kind, permitted decision,
  unanswered state and authenticated addressee checks.
- `human_only`, non-`agent_gate` refs, malformed UUIDs, rich-but-unfetched parts,
  missing rows, unsupported kinds, wrong addressees and invalid authority
  records render **Human action required** notices with no decision controls.
- A gate-read failure no longer fails the transcript/turn read. The notice
  offers **Retry gate verification**; a missing, unsupported, model-only or
  stale proposal offers **Ask Stage 0 to regenerate**, which submits an ordinary
  human-authored recovery turn rather than manufacturing a gate locally.
- ICP **Revise** opens a bounded required-text form and posts
  `decision=revised`, the exact fetched digest, null spend and the trimmed
  `revision_request` through the structured turn route. Approve and Reject send
  no revision text. Backend `GATE_SUBJECT_STALE` and related refusals replace the
  card with an explicit per-gate recovery state.
- An answered gate stays in history only when its immutable answer receipt
  echoes the gate digest and one of the gate's permitted decisions. The recorded
  ICP revision request is projected from that receipt.

#### Human-facing receipt presentation (2026-08-12)

- Durable gate and tool receipts remain authoritative transport records, not
  presentation models. Normal chat projects them through an explicit allowlist
  of business facts such as coverage, proposal name, account count and status.
- Internal ids, object references, hashes, digests, operation keys, tool schema
  versions and backend refusal details never render in the normal transcript,
  gate card, activity labels, recovery copy, source fallbacks or accessibility
  labels. The developer inspector API retains those diagnostics; the chat
  interface no longer exposes an inspector action or drawer (2026-09-20).
- Known operations receive stable human labels. Unknown operations fail closed:
  the transcript shows only a generic activity label and completion state; it
  never renders an arbitrary tool name, input or output payload.
- Decision controls use action language appropriate to the reviewed subject
  (for example, **Approve profile** or **Start research**). Integrity checks
  still send and verify the fetched durable identifiers and digest internally;
  hiding them from the card does not weaken gate authority.

### R3 implementation status (2026-08-10)

- `GET /api/v1/projects/{project_id}` returns the real tenant-scoped project
  shell, honest composer capabilities, and `artifacts: []` until artifact
  integration lands.
- `GET /api/v1/projects/sidebar` returns real tenant-scoped projects and their
  thread summaries through a batch-hydrated projection. Busy and gate status
  are resolved in batches; the endpoint does not fetch each project's threads
  separately.
- The frontend project and sidebar repositories validate these wire payloads.
  HTTP mode neither combines them with fixture records nor accepts fixture URL
  parameters for model, phase, prompt, or context.
- Project rename, pin, delete, and other unsupported project mutations are
  hidden in HTTP mode. Fixture preview mode keeps its local-only controls.
- The project-header hover/click sidebar interaction is intentionally outside
  R3 and remains a later repair slice; this read slice does not claim it.

### R4 implementation status (2026-08-10)

- R4 reuses the atomic Home endpoints implemented in R2; it does not add a
  second project-creation API. Home read, bootstrap request, bootstrap response,
  and refusal envelopes are validated at the frontend repository seam.
- One exact Home draft has at most one request in flight. An unchanged failed
  draft reuses its idempotency key, while editing the message or brand rotates
  that retry identity. A different draft is not disabled by an older request.
- A successful latest submission clears only the submitted draft and navigates
  using only the backend-returned `href`. Network completion order cannot
  navigate an older concurrent draft over a newer one.
- A thread query is resolved only against the real tenant/project-scoped thread
  page. A mismatched thread is never read; the route selects an allowed thread
  and replaces the query with its canonical id, or renders a controlled
  unavailable state when the project has no allowed thread.

### R5 implementation status (2026-08-10)

- The frontend derives three separate values from the effective durable turn
  page: `threadBusy`, the exactly-`running` turn, and queued turns in submission
  order. Stop renders and posts only for the running turn; a queued-only thread
  remains visibly busy without presenting Stop.
- Stream lifecycle transitions temporarily override a stale turn-list response.
  The override is discarded when the canonical read reaches the same or a later
  terminal state, so a delayed `running` response cannot resurrect Stop after a
  terminal frame.
- One exact message request may be in flight only once, while a different
  message remains submittable. This duplicate-click guard does not disable the
  conversation composer while the thread is busy.
- The Stop endpoint now derives the target state from the same submissions-union
  projection used by `GET …/turns`. A new Stop request for a queued or terminal
  turn returns `409 TURN_NOT_RUNNING`; an already-recorded Stop remains an
  idempotent replay.
- Three-turn database acceptance proves A running with B/C queued, Stop A,
  B then C dispatch in order, and the same A/B/C state reconstructs through the
  cold turn-list route during B.

### R6 implementation status (2026-08-10)

- The protected route layout owns one persistent application shell for Home,
  the project catalog, and project workspaces. Those screens no longer mount
  independent sidebars; account routes retain their separately-owned existing
  shell until their lane is joined.
- The desktop project-workspace control implements the ratified
  `collapsed | hover-preview | pinned-expanded` state table. Hover/focus opens
  an overlay without changing content width, click pins and reflows, click while
  pinned collapses, delayed pointer/focus departure dismisses preview, and
  Escape closes preview and restores focus to the trigger.
- The project-header control is a real button with `aria-controls`, truthful
  `aria-expanded` and action labels. It never navigates Home and never exposes
  the former misleading `Go to home` label. Mobile keeps the modal drawer.
- The one mounted sidebar controller re-reads the real tenant-scoped catalog on
  pathname changes. A project created by Home is therefore present after the
  client-side navigation without a full browser restart or fixture fallback.

### R7 implementation status (2026-08-10)

- The real project workspace model contains only durable project metadata,
  advertised composer capabilities, and the exact pre-integration
  `artifacts: []` contract. Fixture-only plan, questionnaire, prompt, phase,
  model, agent-profile, and context-catalog fields are no longer accepted as
  project shell state.
- The project workspace always renders the designed empty Gallery while no
  artifact read contract exists. Fixture cards, artifact-editor controls,
  Target accounts, plan, and questionnaire surfaces are unreachable from the
  project route in both HTTP and fixture transport modes.
- Configuring `CLUE_PROJECTS_API_BASE_URL` selects the HTTP project, Home, and
  sidebar adapters as one set. A backend refusal or network failure remains an
  error state; none can recover through fixture project metadata or artifacts.
- Guessed artifact-detail URLs return not found until a real project-artifact
  read is separately contracted and integrated.

### R8 implementation status (2026-08-10)

- Home and project reads advertise a real, workspace-scoped account/contact
  catalog from Lane C. Ordinary messages and atomic Home bootstrap accept those
  references in user-authored order, validate ownership/current revision and
  applicable contact/account relationships, then persist immutable receipts on
  the submission.
- The fleet worker rehydrates the receipts into `AgentTurnRequest.focus_refs`.
  L5 context assembly retains the submitted ordering, and durable transcript
  reads project the same ordered references back onto the user message after a
  reload.
- The composer keeps one visible model selector, as explicitly ruled for R8.
  Its only option is the server-advertised promoted profile
  `head-of-abm@v32`, labelled **GPT-5.6 Terra** and backed by
  `openai/gpt-5.6-terra`. Its governed gateway baseline requests reasoning
  effort `high`; an explicit environment policy may still override that baseline. The chosen
  profile id is accepted, persisted, and
  checked by the detached worker before the promoted profile is executed.
- Attachments remain unavailable because this deployment has no durable upload
  receipt endpoint. Both Home and project reads advertise `attachments=false`,
  the frontend hides the control in HTTP mode, and the backend refuses any
  attempted attachment receipt instead of accepting a browser-local URL.

### Scene-design reference images (2026-08-24)

The generic attachment capability above remains false. One design-specific exception is live:
while the selected thread has an open **scene** design leg and its ad document is open, the
project composer uploads up to four PNG/JPEG/WebP/SVG inspiration images through the existing
design BFF `POST /assets` seam. These are submitted as ordered `design_asset` `context_refs`,
never as generic `attachment_refs`.

Before accepting the turn, the platform proves EVERY document of the open leg is scene-backed (a
leg holds many documents, not one — 2026-09-19 spec `multi-artifact-design-legs-design.md` §3.7),
and every referenced asset belongs to the workspace, is `ready`, is one of the four image media
types, and still has readable durable bytes. A fifth ref is `422 CONTEXT_REF_LIMIT_EXCEEDED`; missing/cross-workspace
assets or bytes are scoped `404`s. The accepted ids stay on the immutable submission receipt and
become `request.reference_asset_ids` in the design-leg envelope. Transcript reads batch-join the
current asset library only for display metadata (`label`, `media_type`, `thumbnail_digest`). A
reference-only ordinary message may have an empty text body; without a `design_asset` ref, the
existing non-whitespace message rule still applies.

### R9 implementation status (2026-08-10)

- L7 context assembly treats the accepted submission body as the one current
  user instruction and places it last. Capture receipts and attachment
  metadata are system context; queued turns cannot inherit a prior turn's
  prompt as the model-facing instruction.
- A user-requested Stop records a durable `cancelled` journal state after the
  worker has stopped. The submissions-union read reconstructs that terminal
  state after reload, and terminal rendering closes any still-active reasoning
  or activity rows instead of leaving `Thinking` visible.
- `GET …/turns?include=submission_bodies` projects a workspace-scoped
  `submission_message` only until that turn's canonical user message exists.
  Home and ordinary submissions therefore show the exact accepted text before
  the detached worker materializes thread history, without rendering it twice.
- Stream transitions update the selected thread summary immediately. Terminal
  reconciliation refreshes messages, turns, threads, and the shared sidebar
  catalog, so `running` and newly-created project summaries do not wait for a
  browser reload.
- The desktop sidebar trigger remains above its hover overlay, so pointer click
  can pin the preview. Enter and Space invoke the same pin/collapse transition;
  Escape still dismisses an unpinned preview.

### Immutable resource integration ruling (2026-08-16)

The active conversation profile is `head-of-abm@v32`. The pilot bytes remain
authoritative and immutable at profiles `v24`/`v25`, skills `v11`/`v12`, and
recipes `v7`/`v8`; the onboarding lineage remains immutable at profiles
`v26`–`v28`, skills `v13`–`v15`, and recipe `v9`. None of those historical
addresses is rewritten. The former combined lineage at profile `v29`, skill `v16`, and recipe
`v10` also remains immutable. The confirmed-run-v2 lineage at profile `v30`, skill `v17`, and
recipe `v11` remains immutable. The provider-neutral discovery lineage at profile `v31`, skill
`v18`, and recipe `v12` also remains immutable. The active Slice-5 lineage is profile `v32`, skill
`v19`, and recipe `v13`:

- Stage-0 owns `stage0-interview@v19`, trusted readiness `@2`, bounded presentation-bearing
  synthesis `@3`, provider-neutral
  run-start `@3`, the scope-only `open_discovery_configuration_gate@1`, and the durable
  exact-subject `open_icp_confirmation_gate@1` lifecycle;
- FI-2 owns `account-deep-steering@v4` and
  `launch_selected_account_research@1` for exact current-message Account refs;
- production context owns the bounded Client-KB/Product-KB readers and the
  human-addressed `open_product_selection_gate@1` lifecycle;
- the project composer keeps FI-2's typed accepted/failed/not-submitted result
  and clears transferred context only after durable acceptance, while applying
  Stage-0's exact-draft clearing rule so a newer in-flight draft survives;
- project initialization composes the FI-2 handoff/thread destination with the
  Stage-0 conversation-first focus rule for an empty Gallery.

Before this ruling was applied, the configured Singapore target database and
the retained FI-2 final database were audited read-only for queued/running work
carrying Denver's colliding profile or canonical recipe hashes. None existed,
so no hash-keyed compatibility lookup is required. If a future deployment does
contain such a pin, startup must fail closed until those exact bytes can be
resolved; a version-only fallback may not reinterpret it.

This is a union of independent authorities, not a choice of one branch's entire
file. Account selection does not bypass the Stage-0 ICP gate, and the Stage-0
gate does not consume or broaden FI-2's exact Account context.

### FI-2 Slice 9B — selected records as next-message context (2026-08-13)

The Accounts and Contacts tables can prepare up to 100 selected records for an
existing project chat or an idempotently created new chat. This reuses the
composer's existing structured `@` reference system; names and avatars are
presentation, while workspace-scoped ids, object types and canonical versions
are the submitted authority.

`POST /api/v1/projects/{projectId}/composer-context/prepare` accepts:

```json
{
  "thread_id": "thread_01J...",
  "context_refs": [
    {
      "object_type": "account",
      "object_id": "de305d54-75b4-431b-adb2-eb6b9e546014",
      "version": null
    }
  ]
}
```

`thread_id` is nullable for a new-chat destination. The route requires
`thread.write`, validates project/thread/workspace scope and active-thread
state, then returns the exact ordered context entries with current canonical
versions and display-safe labels. It writes no domain state. The actual turn
submission repeats tenancy/version validation and is the only operation that
persists the references in `agent_turn_submission_context_ref`.

The browser transfers the prepared draft through a 30-minute, tab-scoped
`sessionStorage` record addressed by an opaque UUID. A URL never carries entity
ids. Failure to prepare or store leaves the originating selection untouched.
After transfer, the visible composer chips become the editable source of truth.
The refs are consumed only when the turn endpoint accepts that message; failed
submissions keep them, and later messages never inherit them implicitly.

The table action itself is not a research action and requires no confirmation.
It performs no project-membership mutation, provider call or spend. The user
must still write the instruction that explains what the agent should do.

For the explicit same-message instruction to launch deep Account research,
the active `head-of-abm@v32` profile may call
`launch_selected_account_research@1`. This is a narrow FI pilot path, not a
relaxation of `launch_account_research@1`:

- the server derives the initiating human and membership from the captured
  turn, requires `research.launch`, and requires the project run to belong to
  that turn's project;
- every durable context ref must be an Account, and the tool-proposed ordered
  Account ids must equal that exact current-message sequence—no widening,
  duplicates, Contact substitution or inferred project-wide set;
- the latest immutable research directive must name the same set, and the
  server computes the estimate rather than accepting browser/model cost input;
- when `CLUE_BUDGET_CONTROLS_ENABLED=false`, the same explicit command is the
  attributable confirmation receipt, so there is no second confirmation turn;
- when budget controls are enabled, this direct path refuses and the existing
  durable directive gate plus `launch_account_research@1` remains mandatory.

Attaching Accounts without explicit launch language only supplies discussion
context. Attaching Contacts never authorizes Account research. Contact deep
research remains a separately governed selection and launch flow. A successful
launch receipt means queued or replayed, never completed research.

### Post-R9 storage-lifecycle repair (2026-08-10)

- A durable artifact row whose physical blob is gone is a per-message
  `artifact_missing` state. The thread read remains `200`, preserves every
  readable message, and tells the user to resend in a new chat; it never
  invents bytes from a title, label, log, digest, or adjacent prompt.
- A wider storage backend failure is `503 ARTIFACT_STORAGE_UNAVAILABLE`, not
  `artifact_missing` and not a generic internal error.
- If the missing blob is required current/history input, the worker records
  terminal failure code `required_context_artifact_missing`, emits
  `turn.failed`, does not invoke the model with incomplete context, marks the
  fleet task failed, and dispatches the next accepted turn.
- Local API and worker processes that share a database must also share one
  explicit persistent artifact root. Both report the normalized root at
  startup; database clones cannot be reused independently of their blobs.

### Pilot budget-controls — gate amount is optional (2026-08-11)

- The gate amount is **optional on every human-visible surface**. With the
  deployment switch `CLUE_BUDGET_CONTROLS_ENABLED` off (the pilot posture,
  `docs/specs/FI-pilot-budget-controls.md`), `GET …/threads/:threadId/gates`
  serves `max_spend_cents: null` and the rich `gate` stream part omits
  `amount_cents` and `currency`. The amount is withheld, not missing: it stays
  on the immutable gate row for audit and integrity.
- Null rather than `"0"` or `""`, deliberately — a withheld amount must never be
  readable as a real one. The frontend schema accepts null/absent and the
  approval card renders **no cost row at all**: no `$0.00`, no empty currency,
  no dash standing in for a number nobody may see.
- The amount does not gate answerability. `expected_subject_sha256` is the one
  field that makes a card answerable in both postures; a card missing only the
  amount stays clickable.
- `expected_estimated_cost_cents` is nullable at the shared request seam. A
  non-spend ICP gate must send null/omit it; sending any amount is
  `GATE_AMOUNT_UNEXPECTED`. For a spend-bearing gate with controls enabled it
  must echo the exact displayed amount; with controls off the amount check is
  skipped. The `expected_subject_sha256` digest check remains armed in every
  posture and is the load-bearing stale-approval guard.

### Production context-reference read (S6, 2026-08-15)

- `GET /api/v1/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/context-refs`
  is an authenticated, `thread.read`, workspace-scoped read of the exact durable
  context receipt used by that production turn.
- Before assembly commits it returns `data.state: "pending"`. Afterwards it
  returns the bundle schema/policy/counter versions, aggregate hash, assembly
  time, per-layer budgets/counts, and every included/excluded artifact or domain
  reference with its reason code.
- This is not the dev inspector and has no hydration mode. Its schema contains
  no body, text, claim value, evidence span, source URL, email, credential, or
  token field. Exact content remains accessible only through the separately
  governed artifact/knowledge surfaces.
- A foreign project, thread, turn, or workspace is the existing scoped `404`,
  never a response that confirms the object exists.

## Ownership model

```text
Project
├── Thread
│   ├── Message
│   └── Generation run
└── Artifact
    ├── originThreadId
    └── originRunId
```

A Home submission creates a Project and its first Thread atomically. Messages
and generation runs belong to a Thread. Artifacts belong to the Project, so
they stay visible in the Gallery when the user changes threads. Origin IDs keep
every output traceable to the request and run that produced it.

### Ratified first-interaction behavior (2026-08-10)

- The Home submission creates the project with the initial title **`Untitled
  project`**. Its first thread receives a short title derived from the user's
  first message; it is not called `New chat` unless no usable message is
  available.
- Creation is one user action: the project, first thread, first user message,
  and first platform-Deep-Agent turn are accepted atomically. The frontend then
  opens that real thread and begins rendering the response without requiring a
  second Send.
- A new project with no artifacts opens on **Gallery** with an explicit empty
  state. It never borrows fixture artifacts or another project's outputs.
- If a same-thread model turn is active, later user submissions are durably
  accepted in order and shown as **queued**. The composer does not silently
  discard them or disable the product's conversation flow.
- On desktop, hovering the project-header hamburger temporarily overlays the
  expanded main sidebar without resizing the project workspace. Clicking the
  hamburger pins the sidebar open and reflows the workspace; clicking again
  returns it to the collapsed state. Mobile keeps the separate drawer behavior.

## Executable integration contract — founder-ratified 2026-08-10 (R0)

**This section is authoritative over every earlier proposal in this file.** It
defines the target for the frontend/backend repair slices. Existing endpoints
remain authoritative where this section explicitly says "as built"; every
other item is an implementation obligation, not a claim that the route exists.

### 1. Wire, authority, and error conventions

- API JSON uses `snake_case`. Frontend Zod adapters map it once to camel-case
  view models; components never parse or reshape transport payloads.
- Request bodies reject unknown keys. A misspelled or unsupported field is a
  `422 VALIDATION_ERROR`, never a silent no-op.
- The browser calls the origin-relative BFF prefix (normally `/api/clue`). The
  BFF supplies the authenticated session and selected workspace. Browser bodies
  never contain `workspace_id`, `user_id`, `membership_id`, `actor_id`,
  `action_ref`, provider tokens, or provider identity claims.
- Every route re-checks its permission and scopes every read/write by the
  authenticated workspace. A foreign project, thread, brand, turn, context
  object, or attachment returns a scoped `404`; the response does not reveal
  whether that object exists elsewhere.
- Project creation requires the new internal permission `project.write` plus
  `thread.write`. `operator`, `admin`, and `owner` receive `project.write`;
  `viewer` does not. Adding it requires an explicit Lane-B policy-version bump.
- All non-2xx JSON responses use the existing envelope and request header:

```json
{
  "error": {
    "code": "STABLE_MACHINE_CODE",
    "message": "Safe user-facing explanation",
    "requestId": "request-correlation-id"
  }
}
```

The response also carries `X-Request-Id`. Raw provider errors, tool arguments,
private reasoning, stack traces, and prompt bodies never appear in this
envelope.

The stable errors this integration branches on are:

| HTTP | `error.code` | Meaning |
|---|---|---|
| 400 | `IDEMPOTENCY_KEY_REQUIRED` | A required write omitted a usable idempotency header. |
| 401 | `AUTHENTICATION_REQUIRED` / `SESSION_INVALID` | No valid authenticated session. |
| 403 | `WORKSPACE_FORBIDDEN` / `PERMISSION_DENIED` / `MEMBERSHIP_STATE_CHANGED` / `GATE_FORBIDDEN` | The internal principal cannot act in the selected workspace or answer a gate addressed to another user. |
| 404 | `BRAND_NOT_FOUND` / `PROJECT_NOT_FOUND` / `THREAD_NOT_FOUND` / `TURN_NOT_FOUND` / `CONTEXT_REF_NOT_FOUND` / `ATTACHMENT_NOT_FOUND` / `AGENT_PROFILE_NOT_FOUND` / `GATE_NOT_FOUND` | The scoped object cannot be used; foreign-object existence is not disclosed. |
| 409 | `IDEMPOTENCY_CONFLICT` / `CAPABILITY_UNAVAILABLE` / `THREAD_ARCHIVED` / `TURN_NOT_RUNNING` / `GATE_ALREADY_ANSWERED` / `GATE_SUBJECT_STALE` / `GATE_AMOUNT_STALE` | The request is valid JSON but conflicts with durable state or advertised capability. |
| 422 | `VALIDATION_ERROR` / `INVALID_CURSOR` / `GATE_ID_MALFORMED` / `GATE_KIND_UNSUPPORTED` / `GATE_DECISION_UNSUPPORTED` / `GATE_REVISION_REQUEST_REQUIRED` / `GATE_REVISION_REQUEST_UNEXPECTED` / `GATE_AMOUNT_UNEXPECTED` | The request shape, value, gate kind/decision, or pagination cursor is invalid. |
| 500 | `INTERNAL_ERROR` | An unexpected server failure; details stay in correlated logs. |
| 503 | `BODIES_UNAVAILABLE` | This deployment cannot hydrate transcript bodies. |

Unknown future codes remain displayable through their safe `message`, but the
frontend only branches behavior on codes it knows.

### 2. Home read

`GET /api/v1/home` returns the authenticated workspace's configuration for a
new conversation. It returns no suggested project/thread ids and creates
nothing. It requires `project.read`.

```json
{
  "data": {
    "brands": [
      { "id": "brand_01J...", "name": "Clue Demo Brand" }
    ],
    "default_brand_id": "brand_01J...",
    "context_entities": [
      {
        "object_type": "account",
        "object_id": "de305d54-75b4-431b-adb2-eb6b9e546014",
        "label": "Northstar Labs",
        "secondary_label": "northstar.example",
        "image_url": null,
        "version": null
      }
    ],
    "agent_profiles": [
      {
        "id": "head-of-abm@v32",
        "label": "GPT-5.6 Terra",
        "short_label": "GPT-5.6 Terra",
        "description": "Clue's governed GPT-5.6 Terra conversation profile",
        "model_id": "openai/gpt-5.6-terra"
      }
    ],
    "default_agent_profile_id": "head-of-abm@v32",
    "composer_capabilities": {
      "context_refs": true,
      "attachments": false,
      "agent_profile_selection": true
    },
    "suggestions": [
      "Find target accounts for our new campaign"
    ]
  }
}
```

Contract rules:

- `brands` contains only active brands in the selected workspace.
- `default_brand_id` is non-null only when exactly one brand is usable or a
  separately persisted workspace preference names a usable brand. The backend
  never chooses the first row or a lexicographically convenient brand.
- When multiple brands exist and there is no valid default, the frontend must
  obtain a real brand selection before project creation.
- `suggestions` contains zero to three plain-text suggestions. They are not
  project identities or commands.
- A composer control is interactive only when its capability is `true`.
  Unsupported attachment/model/context controls are hidden or explicitly
  disabled; the frontend cannot simulate success.
- When `agent_profile_selection` is false, `agent_profiles` is empty,
  `default_agent_profile_id` is null, and the backend uses its governed default.
- This deployment intentionally advertises one selectable profile. Per the R8
  product ruling, the selector remains visible with exactly the one real
  **GPT-5.6 Terra** option; it is not a decorative multi-model menu.
- When `context_refs` is false, `context_entities` is empty. When it becomes
  true, each entry has the exact `object_type`, `object_id`, `label`,
  `secondary_label`, and nullable `image_url` shape shown in §3's reference
  semantics; the account/contact source remains Lane C's real read layer.

### 3. Atomic Home bootstrap

`POST /api/v1/projects` is the only Home submission route. It requires a
non-blank `Idempotency-Key` header, `project.write`, and `thread.write`, and
accepts:

```json
{
  "brand_id": "brand_01J...",
  "message": "Start an ABM project for Northstar Labs",
  "context_refs": [
    {
      "object_type": "account",
      "object_id": "de305d54-75b4-431b-adb2-eb6b9e546014",
      "version": null
    }
  ],
  "attachment_refs": [],
  "agent_profile_id": "head-of-abm@v32"
}
```

Field rules:

- `brand_id` is required and must name an active brand in the authenticated
  workspace.
- `message` is 1–32,000 characters and must contain non-whitespace text.
- `context_refs` is ordered. The server supplies workspace scope, validates
  each `object_type`/`object_id`/optional positive `version`, and persists the
  same order with the accepted submission. When enabled, one entry is
  `{ "object_type": "account", "object_id": "acct_01J...", "version": null }`;
  `object_type` is one of `account | contact | project_document |
  design_document` for this composer (`design_node`/`design_asset` ride the
  design leg). `project_document` is a Gallery file: `object_id` is the
  document's `id` from `GET /projects/{id}/documents` and `version` is required
  and must equal that listing's `version` (the latest); otherwise `409
  CONTEXT_REF_STALE`. A `project_document` ref on `POST /projects` (Home) is
  refused with `409 CONTEXT_REF_RELATIONSHIP_MISMATCH`. `design_document`
  mentions carry the artifact's `document_id` and `Number(current_version_id)`
  and must belong to the project (`404 CONTEXT_REF_NOT_FOUND` otherwise). Tags
  never open a design leg; the agent decides that by reasoning. (2026-09-17,
  spec `docs/superpowers/specs/archive/2026-09-17-composer-file-tagging-design.md`.)
- `attachment_refs` is ordered and may contain only durable, workspace-scoped
  upload receipts: `artifact_key`, 64-character lowercase `sha256`,
  `media_type`, `byte_count`, and `filename`. Browser blob URLs and local paths
  are structurally forbidden.
- `agent_profile_id` is allowed only when `GET /home` advertised it and
  `agent_profile_selection=true`.
- `context_refs` and `attachment_refs` default to `[]` when omitted;
  `agent_profile_id` defaults to null.
- A non-empty optional capability field sent while its capability is false is
  refused with `409 CAPABILITY_UNAVAILABLE`.
- The client cannot supply the project id, project title, thread id, thread
  title, turn id, phase, run id, `actor_id`, or `action_ref`.

The server performs one transaction, in this order:

1. Resolve and authorize the internal principal and selected workspace.
2. Validate the brand, context references, attachments, and agent profile.
3. Resolve the workspace-scoped idempotency identity and request fingerprint.
4. Create the Project with the exact title `Untitled project`.
5. Create its first Thread with the deterministic message-derived title below.
6. Capture the exact user-message bytes as the content-addressed artifact and
   `onboarding_input` required by capture-before-use.
7. Insert the immutable `agent_turn_submission` receipt with that body
   reference, the authenticated internal user/membership, and every ordered
   reference. Together the capture + submission are the durable accepted user
   message while queued; the fleet worker later materializes the canonical
   `agent_thread_message` row under the existing two-phase turn contract.
8. Append `turn.accepted` and persist the dispatch/queue intent.
9. Commit; only then may the fleet worker observe and execute the turn.

No model/gateway call occurs in the HTTP process. A failure before commit makes
no partial Project, Thread, Message, submission, or dispatch visible.

The first request returns `201`; an exact idempotent replay returns `200` with
the same ids and `replayed=true`:

```json
{
  "data": {
    "project": {
      "id": "prj_01J...",
      "title": "Untitled project",
      "brand_id": "brand_01J...",
      "href": "/projects/prj_01J...",
      "created_at": "2026-08-10T12:00:00Z"
    },
    "thread": {
      "id": "thr_01J...",
      "title": "Start an ABM project for Northstar Labs",
      "href": "/projects/prj_01J.../chats/thr_01J...",
      "status": "running",
      "pinned": false,
      "project_id": "prj_01J...",
      "created_at": "2026-08-10T12:00:00Z",
      "updated_at": "2026-08-10T12:00:00Z"
    },
    "turn": {
      "turn_id": "019f...",
      "thread_id": "thr_01J...",
      "requested_at": "2026-08-10T12:00:00Z",
      "replayed": false
    },
    "href": "/projects/prj_01J.../chats/thr_01J..."
  }
}
```

The frontend navigates only to `data.href`. It does not append `prompt`,
`phase`, `model`, `entities`, or fixture identities, and the project route does
not submit the message again.

Idempotency is scoped to the authenticated workspace and this operation:

- same key + byte-equivalent canonical request → same project/thread/turn;
- same key + different brand/message/ref/profile bytes →
  `409 IDEMPOTENCY_CONFLICT`;
- a network failure after commit is recovered by replaying the same key;
- concurrent requests under one key produce exactly one project and one turn.

Missing/blank keys return `400 IDEMPOTENCY_KEY_REQUIRED`.

### 4. Generated names (since 2026-09-18)

The Home-created thread is born with `title: null`; the project is born as
`"Untitled project"`. Both are placeholders. After the thread's first
**completed** turn (status `completed` or `awaiting_input`, with a non-empty
reply) the server makes one auxiliary model call and writes:

- the thread's `title` — 2 to 5 words naming the task of the chat — only if
  the title is still `null`;
- the project's `title` — 2 to 5 words naming the marketing motion — only if
  it is still `"Untitled project"`.

A manual rename (`PATCH …/threads/:id` or `PATCH /projects/:id`) is never
overwritten: the generated write is conditional on the placeholder. A failed
or slow naming call leaves the placeholder; the next completed turn tries
again. The frontend shows `New chat` / `Untitled project` until a name lands
and refetches the sidebar and project shell on the terminal turn event (and,
while a placeholder is still visible, every 5 s for at most 60 s).

Replaying `POST /projects` with the same key after naming or a manual rename
returns `200` with the current names; the title is not part of the replay
identity.

Historical note: until 2026-09-18 the first thread's title was the message's
first 80 code points (the "R0" rule). Retired.

### 5. Project and sidebar reads

`GET /api/v1/projects/:projectId` requires `project.read` and returns the real
project shell:

```json
{
  "data": {
    "id": "prj_01J...",
    "title": "Untitled project",
    "brand_id": "brand_01J...",
    "product_id": null,
    "status": "active",
    "created_at": "2026-08-10T12:00:00Z",
    "context_entities": [
      {
        "object_type": "account",
        "object_id": "de305d54-75b4-431b-adb2-eb6b9e546014",
        "label": "Northstar Labs",
        "secondary_label": "northstar.example",
        "image_url": null,
        "version": null
      }
    ],
    "agent_profiles": [
      {
        "id": "head-of-abm@v32",
        "label": "GPT-5.6 Terra",
        "short_label": "GPT-5.6 Terra",
        "description": "Clue's governed GPT-5.6 Terra conversation profile",
        "model_id": "openai/gpt-5.6-terra"
      }
    ],
    "default_agent_profile_id": "head-of-abm@v32",
    "composer_capabilities": {
      "context_refs": true,
      "attachments": false,
      "agent_profile_selection": true
    },
    "artifacts": []
  }
}
```

`title` reads `"Untitled project"` until the first completed turn names the
project (§4).

The project response does not contain fixture-only `prompt`, `phase`, `plan`,
`questionnaire`, `previewTimeline`, `reasoningTrace`, or client-manufactured
conversation activity. Threads, transcript, turns, gates, and streams load from
their first-class Lane-D endpoints.

A project with no real artifacts returns `artifacts: []`; the frontend renders
the explicit empty Gallery. It never borrows fixture cards. Until the design
artifact read contract lands, every artifact shown in HTTP mode must come from
a real backend record or not be shown.

`GET /api/v1/projects/sidebar?limit=...&cursor=...` requires `project.read` and
`thread.read` and returns a tenant-scoped, batch-hydrated hierarchy. `limit`
defaults to 50 and is constrained to 1–100:

```json
{
  "data": [
    {
      "id": "prj_01J...",
      "title": "Untitled project",
      "href": "/projects/prj_01J...",
      "conversations": [
        {
          "id": "thr_01J...",
          "title": "Start an ABM project for Northstar Labs",
          "href": "/projects/prj_01J.../chats/thr_01J...",
          "status": "running",
          "pinned": false,
          "updated_at": "2026-08-10T12:00:00Z"
        }
      ]
    }
  ],
  "meta": { "next_cursor": null }
}
```

Project expansion/collapse and desktop pinning are frontend shell state and are
not serialized by this endpoint. Project-level `pinned` is absent because no
project-pin mutation exists. Thread `pinned` is the real as-built thread field.
Thread title may be null for a separately created unnamed thread; the frontend
then renders `New chat` without pretending it is stored.

Conversation status is `idle | running | approval | needs-input | archived`.
Both queued and executing turns derive `running`; `approval` and `needs-input`
derive from unanswered durable gates. This sidebar status is informative and
does not decide whether Stop is available.

**Chat order within a project (2026-10-15).** Pinned chats first, then each
chat by its last message: the newest message row, the person's or the agent's,
or a message the person sent that no turn has answered yet. A turn the server
queued on the person's behalf (a submission with a `derivation`) is not a
message they sent. Renaming, pinning or titling a chat is not a message, so a
chat's `updated_at` no longer decides its place. A chat with no message yet
sorts by when it was created. The frontend keeps the server's order and
re-reads the sidebar when the person sends a message or answers a gate, as well
as when a turn ends. Project order is unchanged.

**Highlight and expansion (2026-10-15).** "Projects" is the highlighted top-level
item only on the projects list. Inside a project no top-level item is
highlighted; on a chat page the chat's own row is the highlight, and its
project's chat list is open: on first load, and again whenever the person goes
to one of its chats, even after closing it.

### 6. Turn submission, queueing, and controls

The as-built ordinary endpoint remains:

```text
POST /api/v1/projects/:projectId/threads/:threadId/turns
```

It requires `Idempotency-Key`, accepts exactly one of `message` or
`gate_response`, and returns `202` with the as-built `TurnAcceptedWire`.
`context_refs`, `attachment_refs`, and `agent_profile_id` use the same shapes
and capability rules as Home bootstrap, but are valid only with an ordinary
`message`; a gate response plus any of them is `422 VALIDATION_ERROR`.
The scene-design exception above is represented only by typed `design_asset`
`context_refs`; `attachment_refs` remains disabled. Its hard cap is four at both
the composer and admission boundary, and the reference set is snapshotted before
the request is queued.

Echoed `context` refs of type `project_document` and `design_document` carry
`label` (the document's own title) and `kind` (the document kind, or
`web|ad`), resolved at read time; the frontend renders the chip from `label`
and never from the id.

The submissions-union read adds an explicit hydration opt-in so a queued user
message survives a reload before the worker has materialized its canonical
history row:

```text
GET /api/v1/projects/:projectId/threads/:threadId/turns?include=submission_bodies
```

Each not-yet-materialized turn item then includes the same user-message wire
shape used by the canonical transcript read:

```json
{
  "submission_message": {
    "id": "...",
    "turn_id": "...",
    "thread_id": "...",
    "sequence": 0,
    "role": "user",
    "body_artifact_key": "sha256/...",
    "body_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "body": "Start an ABM project for Northstar Labs",
    "body_unavailable_reason": null,
    "created_at": "2026-08-10T12:00:00Z",
    "refs": []
  }
}
```

Without the opt-in, `body` is null. Hydration is workspace-scoped,
media-type checked, byte-budgeted, and digest verified exactly like the message
body read. Once the canonical user message exists, the frontend deduplicates
the submission projection and message row by `(turn_id, role=user)`; it never
renders the same human message twice.

Queue rules are binding:

- The public turn-state vocabulary is exactly `queued | running | completed |
  awaiting_input | failed | cancelled`; retry is a new linked turn/generation
  attempt, not mutation of a terminal state.
- At most one platform-Deep-Agent turn has durable state `running` per thread.
- Later accepted turns remain durable `queued` submissions in exact acceptance
  order; reads and reloads must show them before worker execution begins.
- Submission remains available while another turn runs. Per-request duplicate
  protection must not disable the whole conversation composer.
- `thread_busy` means any queued or running turn exists.
- `running_turn` means the one turn whose state is exactly `running`.
- Stop is rendered only for `running_turn`; it never targets a queued turn.
- A terminal `completed`, `failed`, `cancelled`, or `awaiting_input` event
  releases the thread and makes the next queued turn dispatchable.

`POST …/turns/:turnId/stop` records cancellation of the running model attempt
and returns `202`:

```json
{
  "data": {
    "turn_id": "019f...",
    "control_id": "019f...",
    "requested_at": "2026-08-10T12:00:03Z",
    "already_requested": false
  }
}
```

A repeated Stop returns the same durable request with
`already_requested=true`. A queued or terminal target returns
`409 TURN_NOT_RUNNING`. Stop does not undo committed tool effects or suspend a
detached research run.

<a id="chat-polish-delivery-plan"></a>

### 6A. Chat polish delivery plan: Stop, queue, progress and reasoning — 2026-09-12

**Status: implemented in Semarang on 2026-09-12 after founder approval.** CP1–CP6
are built; targeted CP7 acceptance is recorded below. This amendment supersedes
R5's automatic queue advancement after Stop. Normal completion still advances
the queue. Research-card polishing and broader textbox redesign remain separate.

#### Agreed experience and scope

- One composer action switches between Send and Stop. During cancellation it
  remains a disabled Stop icon. After cancellation finishes, the ordinary Send
  icon returns, enabled only when a valid draft exists.
- No visible `Stopping…` or `Stopped` receipt, toast, or transcript placeholder
  for normal cancellation. Remove the old standalone Stop/Working strip. Keep
  machine-readable cancellation state and accessible button semantics.
- A running turn with a nonempty draft offers Send; acceptance queues the new
  message. A running turn with an empty draft offers Stop.
- The action uses the Gallery tab's **4px radius** and existing Clue colors,
  focus, hover, pressed, and disabled treatments. Keep its dimensions stable
  when the icon changes. The shared Home composer receives the same geometry;
  a Home page without an active thread does not acquire a Stop action.
- Chat Stop cancels the current chat generation and design work owned by that
  turn. **Already-launched account/contact research and its fleet continue.**
  This also applies when the stopped turn launched that research.
- Queued messages remain saved and wait for an explicit Resume after Stop.
  Show a compact count and Resume control immediately above the composer.
- Retain accepted user messages/context, committed tool results, saved design
  versions, and the partial user-facing assistant reply. Do not turn interrupted
  work into a successful finalization.
- This slice does not implement a research Stop control, redesign the research
  status card, or change the Home/chat editor layout beyond the queue bar and
  action. The provider-reasoning adapter repair is included as CP1 below, with
  technical detail owned by [AI Elements and reasoning](../architecture/ai-elements-and-reasoning.md#provider-reasoning-delivery-repair).
  Durable partial answers do not imply durable provider-reasoning traces.

#### Button state contract

`hasDraft` uses the composer’s canonical content: meaningful text, selected
account/contact context, or a ready attachment. Whitespace and editor sentinel
characters alone are empty; an attachment upload still in progress does not
bypass the existing submit-validity guard. Reuse that guard rather than create
another definition of a sendable message.

| Turn/control condition | Draft | Action | Behavior |
| --- | --- | --- | --- |
| No running turn | Empty | Send, disabled | Resting state |
| No running turn | Valid | Send, enabled | Submit through the existing repository |
| Turn running | Empty | Stop, enabled | Stop the captured running turn |
| Turn running | Valid | Send, enabled | Accept and queue a new message |
| A send request is awaiting acceptance | Any | Current action disabled | Prevent duplicate submission; clear only accepted draft bytes |
| Stop clicked; request or cancellation pending | Any | Stop, disabled | No second Stop or Send; keep draft editable and preserve new typing |
| Cancellation acknowledged; no newer running turn | Empty | Send, disabled | Return to the resting state |
| Cancellation acknowledged; no newer running turn | Valid | Send, enabled | Preserve text typed during cancellation |
| Queue held after cancellation | Valid | Send, enabled | Append to the waiting queue; only Resume releases the hold |
| Stop rejected or definitely not accepted | Any | Recompute from canonical state | Retain draft; use the existing error surface only for an actual error |

Cancellation-pending takes precedence over a subsequently edited draft. Do not
flip to Send merely because text appears while the backend is still stopping.
An empty Enter press must not stop a turn accidentally: Stop is an explicit
button activation (including keyboard activation of the focused button).
Enter/Shift+Enter/IME behavior for composing messages remains unchanged.

Use accessible names `Send message` and `Stop response`, with disabled/busy
semantics on the control. No new visible lifecycle copy is required. A lost
network connection is not proof of cancellation or completion.

#### Implementation changes

| Area | Previous behavior | Implemented change |
| --- | --- | --- |
| Stop API | Existing authorized, idempotent `POST …/turns/:turnId/stop`; `202` records intent | Reuse it; keep receipt distinct from completion |
| Turn control read | The immutable control row exists, but the turn DTO does not expose pending Stop | Add optional `stop_request` metadata to the turn projection/read and Zod adapter |
| Controller | `stopActiveTurn()` posts, then reloads; no pending guard | Capture the target identity, disable immediately, reconcile until actual terminal state |
| Composer | Send only; standalone Stop lives below the transcript | One typed action view; remove duplicate strip and normal Stopped placeholders |
| Chat worker | Polls control at 0.25s, cancels the task, marks cancelled | Coordinate durable partial preservation and associated design termination before acknowledgement |
| Design execution | Inline driver may abandon its async wrapper while synchronous design continues | Signal the exact design run; retain ownership until it terminates or is safely fenced |
| Design control | Existing `cancel_requested_at`, DAL/API, and per-role model-boundary probe | Reuse this seam; cover dispatch, post-call/tool/write boundaries and recovery |
| Partial answer | Buffered/emitted text survives only in the bounded event outbox | Commit an immutable history artifact/message before terminal acknowledgement |
| Account research | Detached ARV2 jobs continue; worker interruption can suspend/requeue them | Leave their lifecycle untouched by chat Stop |

#### Backend contract and ownership

Keep the public turn states `queued | running | completed | awaiting_input |
failed | cancelled`. Do not introduce a public `stopping` state merely to style
a button. Additive turn-read member:

```json
{
  "stop_request": {
    "control_id": "existing-control-id",
    "requested_at": "2026-09-12T00:00:00Z",
    "pending": true
  }
}
```

It is `null` when absent and is read from `agent_turn_control_request`, never
manufactured by the browser. `pending` is true until the immutable Stop acknowledgement exists. The projection
keeps an accepted Stop running until that acknowledgement; acknowledgement makes
it cancelled even if the worker crashes before publishing the terminal SSE frame. Do not include requester identity
or provider internals in this UI projection. The existing POST receipt remains
`202`; an already-requested Stop remains idempotent; queued/terminal targets
remain `409 TURN_NOT_RUNNING` unless replaying an existing receipt.

The frontend repository validates Stop, Resume and turn-list responses with Zod. The controller keeps an optimistic pending target until
the receipt/read catches up, reconciles through existing SSE plus bounded reads
while cancellation is pending, and rehydrates on reconnect, focus, and reload.
Terminal stream state continues to outrank stale `running` reads. A response for
an old thread/turn cannot disable or reset another thread's action.

The API records intent; the worker coordinates execution. Observe Stop for every
stoppable turn independently of whether a stream emitter or browser SSE reader
is attached; the existing `_execute_watched` early return when `stream is None`
must not become a route through which an accepted Stop is ignored. Inject a narrow
design-cancellation port at the API/worker composition seam, backed by
`subsystems/design/clue_design/runs.py`. Do not import `lumen_agent` or
`lumen_api` internals into frontend code or the chat router. Both design's
existing HTTP cancellation endpoint and chat cancellation use the same DAL
operation; do not add a second provider-facing cancellation implementation or
a loopback HTTP call from a worker to its own server.

#### Cancellation ordering and races

1. **Capture and record intent.** The browser fixes the target workspace,
   project, thread, and running turn when clicked. The server checks current
   authority and state under the existing thread/turn serialization boundary
   and writes/replays the control request plus the thread queue hold atomically.
   Capture the active attempt when
   available; a later unrelated attempt or turn must not inherit stale UI state.
2. **Prevent new work from that turn.** Once intent is observed, stop admitting
   new model calls, tool dispatches, and design dispatches for that turn. Work
   already committed remains. An account-research launch committed before this
   boundary continues; no *new* launch is admitted afterwards.
3. **Signal associated design before abandoning its driver.** Resolve the
   durable turn-to-run relationship. The existing design-leg run ID is derived
   by `design_leg_run_id(turn_id)` and its envelope carries the turn identity;
   validate workspace and ownership, not merely a matching project/document.
   Stamp the existing design cancellation field before cancelling the wrapper.
   Never cancel every run in a project or terminate a shared fleet process.
4. **Close the dispatch race.** A Stop just before run creation must not be
   missed because no run row existed yet. Serialize control acceptance and
   design registration using the same owning-turn lock/check; check the control
   again before executing the registered run. Recovery consults the durable
   intent before any redrive. Reuse the derived identity instead of creating a
   new generic job registry for this single relationship.
5. **Unwind the execution.** Ordinary async chat generation cancels promptly.
   For design, keep the lease/heartbeat while awaiting cooperative termination;
   cancelling `asyncio.to_thread` does not kill its synchronous body. Propagate
   the run-scoped signal to orchestrator, author, reviewer, and their admitted
   work. Check it after an in-flight model call returns and before dispatching
   tools, applying another round, or committing final output. Once cancellation
   is observed, the local run-scoped signal is sticky; a cached negative probe
   must not reopen admission. Existing durable write fences remain the final
   authority against stale execution. A write fence alone is not proof that a
   synchronous body has stopped making provider calls.
6. **Persist the interrupted reply and terminal outcome.** Freeze the accepted
   answer prefix, save its artifact and history reference, and commit the
   cancelled journal outcome using the single-winner transaction described
   below. Only then publish `turn.cancelled` and release the current chat task;
   queued turns remain held until Resume. UI acknowledgement requires the linked design run to
   have ceased execution or be authoritatively fenced from further work/writes.
7. **Recover rather than claim success.** A crash after intent but before
   completion resumes cancellation/partial-save reconciliation, not the stopped
   model. A failed design-control call does not silently count as success. A
   reconciliation deadline must lead to an explicit failure/recovery outcome,
   never an optimistic `cancelled` event while writable design work continues.

**Completion race:** normal finalization and interruption must use one durable
serialization/CAS boundary. If finalization has already committed, preserve it;
late Stop must not overwrite it with a partial reply. If Stop wins, block later
successful finalization and commit interruption once. A model task merely
returning at the same instant is not, by itself, finalization authority. Bind
late callbacks and writes to the original attempt/fence.

**Latency:** the existing 0.25s poll is detection latency, not a promise of total
termination time. Design currently stops at a model-call boundary, so an
in-flight call may finish first. Development must inspect request-scoped
transport cancellation support and cancel/close that request when supported,
without closing a shared client. Do not promise cancellation of provider-side
compute that the provider cannot acknowledge. The release requirement is
prompt local interruption, no further admitted calls/writes after acknowledgement,
and an honest disabled control until cleanup finishes. Measure actual click →
intent → worker observation → child terminal → chat terminal intervals.

#### Durable partial answers and preserved context

- Persist only the user-facing assistant answer prefix from the existing
  finalize-argument text path. Exclude tool arguments, ordinary provider chatter,
  and reasoning parts. Keep its exact bytes; an unfinished Markdown fence must
  remain an unfinished fence and render safely.
- Flush the emitter's in-memory pending answer bytes before freezing the prefix.
  Use the existing attempt/part IDs and ordered delta indices to reconcile the
  emitted outbox prefix with pending text, without duplicated chunks. A worker
  recovery can use the outbox up to a recorded cutoff; retain those events while
  interruption reconciliation is outstanding. Do not claim durability for
  unreceived provider tokens or unflushed memory lost in a process crash.
- Reuse the artifact store, `agent_thread_message`, and history artifact-ref
  tracking. Use the same deterministic assistant identity as the normal
  finalization path so reload/retry cannot create two replies for one turn.
  An empty prefix creates no fabricated assistant text.
- Write artifact bytes first, then commit the history pointer, artifact
  ownership reference, and cancelled journal outcome together under a shared
  transaction/turn lock. Existing history helpers open their own transactions;
  factor a transaction-aware DAL seam rather than chaining independent commits
  and assuming they are atomic. If a crash leaves an unreferenced blob, replay
  attaches the same content address idempotently. If storage fails, do not
  acknowledge a preserved partial answer; retain/retry the durable stop intent.
- An interruption is not an `AgentFinalizeEnvelope` claiming success. Persist
  its terminal outcome separately using the existing cancelled journal path,
  and reconcile crash windows and races with `agent_finalization_commit`.
- The canonical message read plus terminal turn state identifies the answer as
  interrupted. Extend the typed message/history projection only where necessary;
  derive interruption from the owning turn instead of adding competing status
   sources. The frontend keeps the partial body with no visible Stopped badge.
   Put this provenance into the existing context-assembly contract and tests,
   including both ordinary conversation and design-leg history readers.
  Context assembly receives that body with explicit interrupted provenance, so
  the next model does not mistake it for a finished recommendation. Preserve the
  original bytes; do not append synthetic wording to the saved user-facing body.
- Accepted user context references and committed tool outputs remain in their
  existing durable stores. Research jobs and their new results can continue to
  update the account/research views independently of chat cancellation.
- Scene design keeps already-accepted authoring rounds/document versions.
  Website mode currently persists at the end: keep the existing committed
  website intact and reject unfinished candidate output. Do not introduce web
  checkpointing or apply an unvalidated page as part of this Stop slice.
- Reuse existing retention, artifact erasure, tombstone, and authorized hydration
  rules. A hard refresh after SSE pruning must load the partial reply from
  durable history; cold load must not depend on replaying temporary events.

#### Waiting queue and Resume — founder-selected direction

Stop A leaves accepted B/C saved in FIFO order, with no automatic execution.
This requires a backend queue hold; hiding a frontend callback cannot implement it.

**Minimal presentation:** one compact row directly above the composer, aligned
with its edges: `2 queued messages` on the left, `Resume` on the right. Use the
same Clue text/button styling and 4px radius. Do not add reordering, editing,
deleting queued messages, a new queue drawer, or lifecycle banners in this slice.
Existing queued transcript entries stay visible. Normal running queues can show
their count; Resume is shown only for a held queue. During cancellation Resume
is disabled. After cancellation it is enabled; while its request is pending it
is disabled again. No Stopping/Stopped copy is introduced.

**Implemented backend contract:**

- Persist one queue-control record per workspace/thread, keyed by the existing
  Stop control ID, with the hold timestamp. It is shared dispatcher state, not
  localStorage or a new enum value for every queued turn. B/C remain `queued`.
- Accept Stop and set its hold in the same thread-lock transaction. Check this
  record at `dispatch_next_thread_turn` before any enqueue. Worker completion,
  submission, dispatch-on-attach, sweeper and recovery all use that guard. Already
  offered but unstarted agent-turn work must also recheck the hold before model
  execution, closing the enqueue/claim race. Do not acknowledge Stop if another
  queued turn can slip through behind it.
- Add typed `meta.queue_control = { paused, hold_control_id, paused_at }` to the
  existing turn-list read. Derive queue counts/order from its queued submissions.
  Optional defaults keep old payloads readable. After reload, rehydrate both the
  held queue and disabled/enabled Resume state from server truth.
- Add `POST /projects/:projectId/threads/:threadId/queue/resume`, through the same
  authenticated BFF/repository seam. Body carries the observed `hold_control_id`,
  never an arbitrary next-turn ID. Require thread-write authority, same workspace
  and project scope, and no still-pending cancellation.
- Under the thread lock, clear exactly that hold and dispatch the oldest eligible
  queued turn using the existing dispatcher. Return a typed `202` receipt with
  the resulting queue-control snapshot and dispatched turn ID, if any; acceptance
  is not model completion. Resume creates no new user message and consumes no
  draft. Retrying the same Resume must not dispatch twice or clear a later Stop's
  hold. A changed hold or pending cancellation returns a typed conflict and causes
  rehydration. Preserve a replayable control identity/audit receipt for this.
- Sending while held appends a valid new message at the end; it does not resume
  the queue implicitly. The user must choose Resume to continue B, then C, then
  newly accepted messages. A failed submission does not erase the draft.
- If no queued submissions remain when cancellation is acknowledged, clear that
  empty hold under the thread lock and omit the queue bar. A later new Send starts
  normally. Serialize that check with submissions so a just-accepted message
  cannot be stranded invisibly or bypass a nonempty hold.
- A hold applies to chat turns in this thread only. Research progress and unrelated
  threads/design jobs are unaffected. Normal completion without Stop still advances
  the queue automatically.

**Completion race refinement:** if finalization wins before Stop is accepted,
do not create a hold from the rejected stale Stop. If the Stop/hold transaction
wins first, normal finalization must observe that intent and take the interruption
path even if its model task returns before the polling watcher wakes. Saved
domain work remains, and B/C remain held. Do not decide the winner from task
scheduling order or stale frontend state.

#### Development slices and concrete ownership

The approved slices below retain their finish conditions; the verification record
distinguishes deterministic coverage from live observations.

| Slice | Deliverable and primary files | Finish condition |
| --- | --- | --- |
| CP0 — Freeze contract | This §6A, reasoning delivery plan, matching §3.5 amendment in `docs/specs/FI-lane-D-production-chat-and-launch.md` | Review the selected button/queue rules, cancellation scope, partial-history truth and additive API payloads; no invented public lifecycle states |
| CP1 — Restore real reasoning delivery | Gateway provider adapter and tests, `chat/turn_stream.py`, existing reasoning disclosure; see linked technical plan | A real supported-provider trace survives adapter → event stream → browser; no ordinary text/tool leakage, duplication or horizontal overflow |
| CP2 — Interruption persistence | `agent_turn_wiring.py`, `chat/turn_stream.py`, `chat/message_bodies.py`, `conversation_capture.py`, `platform/agents/clue_agents/ports.py`, relevant projections | Exact partial body and interrupted context survive cold load/outbox pruning; finalization race and retry are idempotent |
| CP3 — Chat/design cancellation | `chat/turn_controls.py`, `chat/stream.py`, `agent_turn_fleet_wiring.py`, `design_leg_wiring.py`, `design_fleet.py`; design DAL and `lumen_agent/cancellation.py`/harness boundaries as needed | Exact owned design run stops without detached continuation/redrive; partial-save and design acknowledgement precede terminal chat event; research continues |
| CP4 — Durable queue hold/resume | `agent_turn_submission.py`, control routes/DAL, turn projections and a reversible migration; `data/chat-turns.repository.ts` | Stop holds FIFO submissions across every dispatcher/recovery entry; scoped idempotent Resume releases exactly the observed hold |
| CP5 — Read/controller contract | `platform/projections/clue_projections/threads.py`, chat schemas/routes; frontend `model/chat-turn.ts`, `data/chat-turns.repository.ts`, `hooks/use-project-chat-controller.ts` | Pending state survives refresh; typed receipt handling, terminal precedence, duplicate clicks, wrong-thread replies and uncertain network outcomes covered |
| CP6 — Composer presentation | A pure action selector/controller in `features/projects/model` or `hooks`; `project-composer.tsx`, `conversation-content.tsx`, `chat-transcript.tsx`, `project-flow.module.css`, a small queue-bar view and composition callers | Button-only lifecycle and queue count/Resume match the matrix; old Stop strip and Stopped placeholder removed; no layout jump or draft loss |
| CP7 — Integrated acceptance | Existing chat/design suites plus focused regressions and a Semarang browser/API/DB walk | Cancellation, partial-history, research isolation, queue and accessibility evidence below passes; deployed processes use this checkout |

Keep transport/state decisions in repositories/controllers, not JSX. Extend the
existing store/control protocols rather than writing parallel cancellation
systems. Schema changes are justified by a concrete invariant (for example a
selected durable queue hold); if needed, use a random Alembic revision, one head,
and an up/down/up smoke test on an isolated throwaway database. Prefer no new
runtime flags; any required flag must land with `.env.example` parity.

#### Implementation and verification record — 2026-09-12

- `d639a2de8bd1` adds an immutable `agent_turn_stop_ack`, the thread's
  `queue_hold_control_id`, and idempotent `agent_thread_queue_resume` receipts.
  Existing cancelled controls are backfilled. The migration has one head and
  passed isolated up/down/up before being applied to `clue_semarang`.
- Stop, finalization, design registration, queue admission and interruption
  persistence share the relevant thread/turn locks. Queue acceptance timestamps
  are assigned monotonically under the thread lock, so a transaction opened
  earlier cannot overtake messages already accepted. Claims recheck queue holds.
- `chat/interrupted_turn.py` reuses artifact storage, immutable history and
  ownership references. It persists only the last accepted finalize-answer prefix.
  Recovery retains pending Stop events, never restarts the stopped model, and
  can hydrate history after event pruning. Interrupted provenance and its body
  share one context-budget decision; the saved user-facing bytes stay unchanged.
- The new Resume endpoint returns `hold_control_id`, `replayed`,
  `dispatched_turn_id` and `queue_control`. Stop returns the existing 202 intent
  receipt. Turn reads add `stop_request.pending` and `meta.queue_control`.
- Design uses its existing cancellation DAL. The exact turn-derived run is
  signalled before driver cancellation; its heartbeat/lease remains until the
  synchronous body exits. Model-start/end checks force a fresh probe, streaming
  token checks observe the sticky signal, and the design toolbelt blocks further
  writes. This is cooperative cancellation: an in-flight synchronous provider
  request may return or time out before acknowledgement. Shared clients/workers
  and detached research jobs are never killed by chat Stop.
- Focused backend tests cover real adapter wire data through the emitter,
  interrupted history/replay/outbox pruning, both Stop/finalization orderings,
  queue hold/Resume/FIFO and stale Resume, claim-before-start, inline design lease
  ownership and design cancellation boundaries. The frontend project suites
  pass 202 tests, including button states, reasoning wrapping and repository
  contracts. Design-system build, lint and production build pass; lint retains
  two pre-existing unused-variable warnings in design-engine files. Import-linter
  reports 26 contracts kept. Mypy still reports four pre-existing errors in
  unchanged `design/ad_assets.py`, `arv2/account_research_claims.py` and
  `arv2/account_research_driver.py`.
- Live Semarang acceptance used a dedicated verification chat. Grok emitted
  13 reasoning deltas in the first turn; the disclosure showed real text and
  respected manual collapse. Trace width and scroll width were both 669px.
  Long inline-code/Markdown responses stayed within the 1086px page after reload.
  A second turn was stopped while reasoning: intent-to-ack was 0.353s, with no
  fabricated assistant reply or successful finalization. Its queued successor
  remained held across hard reload and completed only after Resume. All five
  verification turns finished; no test generation remains running.
- Evidence limits: the live Stop happened before answer text; exact partial-answer
  preservation is verified deterministically against Postgres/artifact hydration,
  including pruning. Design scene/website cancellation was exercised with local
  runtime tests, not a new paid live design generation. No new live account
  research was launched for this acceptance; isolation is enforced by the scoped
  cancellation paths, and existing Semarang research work was left untouched.
  These observations do not claim provider-side compute cancellation or durable
  customer-visible reasoning. Semarang runs frontend 3040, API 8070, design 8071,
  database `clue_semarang`, and dedicated Redis 56379; sibling services were untouched.

The following matrix remains the regression checklist for future changes:

#### Acceptance matrix and verification

1. **Button/keyboard:** cover every matrix row, whitespace-only draft, context-
   only draft, ready/in-progress attachments, IME composition, Enter on empty,
   keyboard Stop, rapid double click, typing during Stop, successful/failed
   Send, and matching 4px geometry without width changes.
2. **Authority and races:** repeated Stop returns one control; other workspace,
   project, thread, or queued target cannot be cancelled. Stop racing completion
   produces exactly one authoritative outcome and assistant body. Two tabs and
   delayed HTTP/SSE messages cannot restore an obsolete Stop button.
3. **Durability:** cancel before first text, during a long reply, and between
   tools; compare live prefix with saved body/digest. Hard reload, new session,
   worker restart, and expired/pruned SSE must retain the same accepted messages,
   partial answer, tool results and interrupted-context meaning. Exercise crashes
   after blob write, before/after DB commit and before terminal event publication.
4. **Design:** stop before registration, between registration/start, during a
   model call, between a model result and tool/write, during author/reviewer work,
   and just as normal completion commits. Repeat for scene and website paths.
   Prove no additional calls/writes occur after acknowledgement, saved scene
   versions remain, website base is unchanged when unfinished, and lease expiry
   or worker takeover cannot restart cancelled generation. Include any admitted
   nested design work discovered by the execution-path inventory.
5. **Research isolation:** run account research alongside the stopped chat/design
   turn, including a run launched by that turn. Observe continued job progress
   and durable results; assert no cancellation/suspension/requeue caused by Stop.
   Other chats, design runs, projects, and workspace processes remain untouched.
6. **Queue:** A running with B/C queued; Stop holds B/C across reload/restart and
   every dispatcher/claim entry. Resume during cancellation is rejected; repeated
   Resume starts B exactly once, then C in order. Sending D while held leaves
   B/C/D waiting. Test stale Resume against a newer hold, rejected Stop after
   completion, accepted Stop racing completion, and empty-hold cleanup racing
   submission. No queued message is lost, duplicated or silently cancelled.
7. **Rendering:** partial Markdown, unfinished backticks/fences, long URLs and
   unbroken strings remain within narrow chat panels. No new horizontal scrollbar
   or restoration of duplicate reasoning/activity receipts. Genuine errors remain
   actionable; normal cancellation adds no lifecycle text.
8. **Reasoning:** real provider-backed evidence covers streaming, multiple rounds,
   manual collapse, final answer and Stop. Keep the existing plain-text trace and
   long-content safeguards. Verify trace delivery separately from partial-answer
   persistence and do not promise unavailable private/encrypted provider content.

Start with `tests/api/test_lane_d3_turn_stream_db.py`,
`tests/api/test_lane_d2_turn_submission_db.py`,
`tests/projections/test_thread_shell_db.py`,
`tests/api/test_p34_design_leg_engine_db.py`,
`tests/design/test_design_fleet_turns_db.py`, and
`tests/design/test_design_fleet_reaper_db.py`, plus the design runtime/API
cancellation tests. Use deterministic provider stubs for race/crash coverage,
then a bounded real provider-backed turn for final delivery/cancellation proof.
Do not treat a visual fixture as that proof.

Frontend gate: focused controller/model/stream regressions, then
`npm run design-system:build`, `npm run lint`, and `npm run build`, followed by
browser checks. Backend gate: focused affected suites, Ruff/type/seam checks and
required repository checks; attribute unrelated existing failures explicitly.
Use Semarang-only app paths and runtime ownership checks. DB tests use their own
Semarang test database; manual acceptance uses `clue_semarang`. Never drain,
restart, migrate, or stop a sibling workspace's services. Record IDs, statuses,
counts and timings without copying private conversation/trace content into docs.

**Release criterion:** the work is complete only when the real button controls
the exact running chat/design work, durable reads preserve accepted progress,
independent research demonstrably continues, and the UI shows only the agreed
control states. A successful POST or a changed icon alone is not acceptance.

### 7. SSE control frames and terminal lifecycle

Every SSE frame carries an `event:` name and one JSON `data:` object. The
`event:` name must byte-equal `data.type`. The frontend treats disagreement as
a protocol failure and rehydrates from durable state; it never guesses.

Durable frames keep the as-built envelope:

```text
schema_version, event_id, sequence, occurred_at,
project_id, thread_id, turn_id, type,
generation_attempt_id?, message_id?, part_id?, part_kind?, run_id?,
delta_index?, part?, delta?, reason?, status?, failure_code?, replayed?
```

Connect-generated frames are deliberately cursorless but still carry the
common identity and discriminator:

```json
{
  "schema_version": "1",
  "project_id": "prj_01J...",
  "thread_id": "thr_01J...",
  "turn_id": "019f...",
  "type": "stream.hello"
}
```

```json
{
  "schema_version": "1",
  "project_id": "prj_01J...",
  "thread_id": "thr_01J...",
  "turn_id": "019f...",
  "type": "stream.reset",
  "reason": "cursor_older_than_horizon",
  "rehydrate": "transcript"
}
```

Synthetic frames never invent `event_id`, `sequence`, or `occurred_at`.
A durable reconciliation `stream.reset` keeps its real durable cursor.

The turn stream is finite:

- backlog containing a terminal event is emitted through that event and closes;
- a live batch containing a terminal event is emitted through it and closes;
- the frontend finalizes immediately when it parses the terminal event, aborts
  its reader, hides Stop, and refreshes the canonical transcript; it does not
  wait for socket EOF to update the UI;
- reconnect occurs only while durable state remains queued/running;
- `stream.reset` causes transcript/turn rehydration before any new attach.

Malformed non-terminal frames are diagnostic telemetry, not transcript
messages. An unsupported schema version or identity mismatch stops the stream,
shows a controlled recovery state, and re-fetches durable data. Raw strings
such as `malformed turn-stream frame` never appear as chat content.

### 8. Sidebar interaction state

The project header hamburger controls one shared authenticated application
shell; it is not a navigation link. Desktop states are:

```text
collapsed | hover-preview | pinned-expanded
```

- Pointer hover or keyboard focus from `collapsed` enters `hover-preview`.
- `hover-preview` is an overlay and does not change workspace width.
- Pointer/focus departure returns to `collapsed`; Escape also closes preview.
- Click from collapsed/preview enters `pinned-expanded` and reflows the project
  workspace.
- Click while pinned returns to `collapsed`.
- Mobile uses the existing modal drawer and does not reuse desktop reflow.

The button exposes its true action through `aria-label` and `aria-expanded`.
It never calls `router.push("/")` and never uses the label `Go to home`.

### 9. Capability honesty and fixture prohibition

In HTTP mode:

- Home, project, sidebar, threads, messages, turns, gates, and stream adapters
  all use HTTP repositories behind the same transport selection.
- An error stays an error. No repository catches it and substitutes fixture
  projects, threads, artifacts, messages, models, accounts, or contacts.
- Generic attachments stay hidden. The only upload affordance is the scene-leg
  reference-image exception above, backed by the design asset registry and durable bytes;
  it does not advertise or populate generic `attachment_refs`.
- Model selection is visible because the backend advertises the one real Terra
  profile and persists the chosen `agent_profile_id` on every message
  submission. No second/decorative option is rendered.
- Context chips are visible because the backend advertises the real Lane C
  catalog and persists/rehydrates the ordered references.
- Project rename/pin/delete and project-wide archive controls stay hidden until
  their real endpoints are separately contracted and implemented. Thread-level
  rename/pin/archive remain available through the as-built thread endpoints.
- Fixture-only phase simulation and query parameters are allowed only in
  explicitly fixture/dev preview routes, never in an HTTP-backed project URL.

Fixture adapters may remain for isolated visual tests, but they must implement
the same repository interfaces and lifecycle semantics. They are not a
production fallback.

### 10. R0 acceptance obligations for later slices

Implementation is conformant only when contract tests prove:

1. One Home action creates one durable project/thread/capture/submission.
2. Idempotent retry cannot duplicate any of those rows.
3. Cross-workspace brand/project/thread/ref/attachment access reveals nothing.
4. The response route contains only backend-returned project/thread ids.
5. A new project renders an empty Gallery with no fixture cards.
6. Queued turns survive reload and execute in order.
7. Stop is offered only for the running turn and disappears on terminal.
8. `stream.hello`/`stream.reset` parse and every turn stream closes on terminal.
9. Sidebar hover overlays, click reflows, and neither action navigates Home.
10. Every visible composer control either completes its durable contract or is
    absent from HTTP mode.

---

The sections below preserve the original frontend proposal and the 2026-08-08
as-built amendments for history. Where they conflict with the executable
contract above, the executable contract wins.

## Historical frontend proposal — read endpoints (non-authoritative)

### `GET /api/v1/projects/sidebar`

Returns the compact project/thread hierarchy used by the persistent product
sidebar. It is intentionally smaller than the complete Project workspace
resource so account, contact, and Home routes do not fetch artifact payloads.

```json
{
  "data": [
    {
      "id": "10m-landing-page-campaign",
      "title": "10x revenue campaign",
      "href": "/projects/10m-landing-page-campaign",
      "expanded": true,
      "pinned": true,
      "conversations": [
        {
          "id": "thread-primary",
          "title": "Landing page concepts",
          "href": "/projects/10m-landing-page-campaign?thread=thread-primary",
          "status": "idle"
        }
      ]
    }
  ],
  "meta": { "total": 1 }
}
```

Conversation status is one of `idle`, `running`, `review`, `approval`, or
`needs-input`. These values express workflow meaning; the frontend owns their
icons, badge copy, and colors. `expanded` is an initial preference only—the
current frontend shell keeps expand/collapse state locally until user
preferences are connected.

### `GET /api/v1/home`

Returns the Home composer configuration, selectable account/contact entities,
available models, and three recommendation prompts. The Home response no longer
contains a project collection; Projects are intentionally absent from this
surface.

File attachments are browser-owned draft state until submission. The eventual
`POST /api/v1/projects` request should use `multipart/form-data` when files are
present and send the prompt, model ID, entity IDs, and attachments together.
The draft view model follows AI SDK `FileUIPart` fields (`type`, `mediaType`,
`filename`, and `url`) plus frontend-only `id` and upload `status` fields. Blob
URLs are preview-only and must never be sent as backend file identifiers.

### `GET /api/v1/projects/:projectId`

Returns the complete project shell:

```json
{
  "id": "10m-landing-page-campaign",
  "title": "10m+ landing page campaign",
  "prompt": "design a landing page",
  "defaultModelId": "gpt-5.5",
  "models": [],
  "contextEntities": [
    {
      "id": "openai",
      "label": "OpenAI",
      "type": "account",
      "imagePath": "/logos/openai.svg",
      "secondaryLabel": "www.openai.com"
    }
  ],
  "threads": [
    { "id": "thread-primary", "title": "ad design" }
  ],
  "generationSteps": [],
  "artifacts": [
    {
      "id": "landing-page-sharper-abm",
      "title": "Landing page sharper ABM - OpenAI",
      "type": "website",
      "imagePath": "/projects/gallery/abm-anthropic-light.png",
      "editedLabel": "Last edited today",
      "originThreadId": "thread-primary",
      "originRunId": "run-abm-001"
    }
  ]
}
```

Valid artifact types are `table`, `website`, `canvas`, and `presentation`.

The current project response also includes `conversationActivity.tools` and
`conversationActivity.sources`. These fixture-backed records supply tool names,
parameters, results, and external evidence to the typed message adapter. They
must be backend-owned in production; presentation components do not create
them.

`contextEntities` is the searchable account/contact catalog available to the
project composer. Selected entities are atomic inline references in the prompt
editor, but they remain ordered structured IDs in draft state; the visible logo,
avatar, and label are presentation only. The message endpoint should accept
`contextEntityIds: string[]` alongside the plain prompt so Aaryan can resolve
fresh CRM context without parsing visible mention text.

Messages render as ordered, validated parts. The current frontend contract
supports `text`, `reasoning`, `action`, `tool`, `plan`, `task`, and `sources`
parts. Each part requires a stable ID so streamed updates can replace a part in
place rather than append duplicate status UI.

## Historical frontend proposal — write endpoints (non-authoritative)

- `POST /api/v1/projects` — atomically create an `Untitled project`, its first
  Thread (short title derived from the first user message), the first Message,
  and the first platform-Deep-Agent turn. Return the real project/thread/turn
  identities needed to open the conversation and stream immediately.
- `POST /api/v1/projects/:projectId/threads` — create another thread inside the
  existing Project.
- `PATCH /api/v1/projects/:projectId` — rename the project or update its pinned
  state from the sidebar.
- `DELETE /api/v1/projects/:projectId` — remove the project after confirmation.
- `POST /api/v1/projects/:projectId/threads/archive` — archive the project's
  visible chat history without deleting its artifacts.
- `POST /api/v1/projects/:projectId/threads/:threadId/messages` — append a user
  or assistant message. User messages may include `contextEntityIds` alongside
  the text and file attachments.
- `POST /api/v1/projects/:projectId/runs` — start artifact generation from a
  message and return the run ID.
- `GET /api/v1/projects/:projectId/runs/:runId` — return generation state and
  step progress. This can become an SSE endpoint without changing the UI.
- `GET /api/v1/projects/:projectId/artifacts` — list the project Gallery,
  independent of the active thread.
- `PATCH /api/v1/projects/:projectId/artifacts/:artifactId` — update artifact
  metadata or editable canvas content.
- `PATCH /api/v1/projects/:projectId/artifacts/:artifactId/nodes/:nodeId` —
  update the selected canvas node properties shown by the inspector.

### Sidebar mutation payloads

The sidebar currently performs these mutations through its fixture controller.
The HTTP implementation should preserve the same response shapes so the
presentation tree can switch repositories without changing its components.

Create a thread:

```http
POST /api/v1/projects/:projectId/threads
Content-Type: application/json

{ "title": "New chat" }
```

Return `201` with the created sidebar conversation:

```json
{
  "data": {
    "id": "thread_01J...",
    "title": "New chat",
    "href": "/projects/project_01J...?thread=thread_01J...",
    "status": "idle"
  }
}
```

Rename or pin a project:

```http
PATCH /api/v1/projects/:projectId
Content-Type: application/json

{ "title": "Enterprise account research", "pinned": true }
```

Both fields are optional, but at least one must be present. Return `200` with
the updated project summary using the `SidebarProjectSchema` fields.

Archive visible chat history:

```http
POST /api/v1/projects/:projectId/threads/archive
Content-Type: application/json

{}
```

Return `202` when archival is asynchronous or `204` when it is complete.
Artifacts, artifact versions, account context, and run lineage must remain
attached to the Project. Archiving chat history is not project deletion.

Remove a project:

```http
DELETE /api/v1/projects/:projectId
```

Return `204` after the backend applies the agreed retention policy. The
frontend requires an explicit confirmation before calling this endpoint.

Mutation failures use the shared error envelope and must include a stable
`requestId`. Return `404` for an unknown project, `409` for a stale or invalid
state transition, and `422` for schema validation errors.

The current inspector shell exercises text `color`, `fontFamily`, `fontSize`,
`fontWeight`, and `textAlign`; button `label`; and image `fit`, `radius`, and
replacement-file fields. The frontend keeps these edits local until the node
PATCH endpoint is connected.

## Historical frontend-only preview state (non-authoritative)

The `thread`, `phase`, `prompt`, `model`, and comma-separated `entities` query
parameters exist so approved
Figma states can be opened directly. Valid phases are `conversation`,
`questionnaire`, `agent-running`, `planning`, `generating`, and `complete`.
Preview transition timing and progress milestones live in the fixture-backed
`previewTimeline` field rather than presentation components. They demonstrate
interaction and motion only; replace them with the generation-run resource when
the backend is connected.

---

## Project and chat rename amendment — founder-requested 2026-09-12

This amendment supersedes earlier statements that project renaming is unsupported. The
founder requested persistent project labels from the sidebar three-dot menu and verification
that chat names survive refreshes and new sessions.

- `PATCH /api/v1/projects/:projectId` accepts exactly `{ "title": string }` and returns
  `200 { "data": { "id": string, "title": string } }`. Titles are trimmed, nonblank, and
  limited to 200 characters. Unknown fields (including `pinned`) are rejected with 422.
- Requires the active membership's `project.write` permission. The HTTP boundary invokes
  `rename_project@1` through the existing journaled toolbelt. The spine updates `project.name`
  only where both project and workspace IDs match. Foreign and missing projects both return
  404; permission refusals return 403. Optional Idempotency-Key follows the chat tool convention.
  Identity, brand/product associations, status, threads and contents remain unchanged.
- The frontend uses the project repository and authenticated same-origin `/api/clue` BFF.
  Rename project opens a name field with Save/Cancel; saving blocks repeated submission, and a
  failed save retains the draft with an error. Labels update only from the successful server
  response. The sidebar and project reads reload through the shared catalog invalidation.
- Chat renaming continues to use `PATCH …/threads/:threadId` and `rename_thread@1`, persisting
  `agent_thread.title`. Its saved response updates the header and invalidates the sidebar.
  All fresh reads use server state, with no browser-storage title override.
- This adds no project pin/delete operation, no agent-profile grants, and no new runtime flag.
  Fixture mode does not offer project rename; it requires a connected workspace.

## Projects directory and project home — as built (2026-09-19)

**Authoritative for the projects directory (`/projects`), the project home (`/projects/{id}`),
the project's standing instructions, and the project's human memory notes.** Design record:
`docs/superpowers/specs/2026-09-19-projects-directory-and-home-integration-design.md`
(the plan is `docs/superpowers/plans/2026-09-19-projects-directory-and-home-integration.md`).
This section records what the backend actually serves; where the spec and the code differ, the
code is what is written here and the difference is called out.

**What this supersedes.**

- It supersedes the 2026-09-12 rename amendment's line "Unknown fields (including `pinned`) are
  rejected with 422". `PATCH /api/v1/projects/:projectId` now accepts `{title?, description?,
  pinned?}` and requires at least one of them.
- It supersedes §9's line "Project rename/pin/delete and project-wide archive controls stay
  hidden until their real endpoints are separately contracted and implemented" **for pin and
  archive only**. Both now have real endpoints and are visible. **Project delete still does not
  exist** — archive is the reversible removal, and no destructive project endpoint is contracted.
- The historical frontend proposal above (`GET /projects/directory` as one aggregate read, plus
  the client-side command bus and its localStorage store) **was not adopted**. It remains in this
  file as the historical proposal it is labelled as. Production uses the paginated read and the
  governed per-mutation writes below.

**System projects are invisible everywhere a human looks.** `project.kind` is `'marketing'` or
`'system'`; the per-brand onboarding anchors are `kind = 'system'`. They are never served by the
directory, the archived view, the sidebar, the project shell, the instructions routes or the
memory routes. The write tools refuse them with the reason code `project_system`, which this HTTP
surface reports as **`404 PROJECT_NOT_FOUND`** — naming a system project would disclose a project
the human never filed. (The spec's §4 table listed a distinct `PROJECT_SYSTEM` 404 code; the code
deliberately does not emit one.)

**`updated_at` is a composite, not a column read.** Every directory and sidebar row serves
`GREATEST(project.updated_at, MAX(agent_thread.updated_at))` over that project's **non-archived
(`status = 'active'`) threads**, so the *Last updated* sort reflects conversations without a write
per turn. The stored `project.updated_at` is bumped by details edits, rename, archive/restore, an
instructions save and a memory write; **pinning does not bump it**, and neither does the
conversation namer.

**The conversation namer never renames a human-named project.** `set_project_name_if_untitled`
updates only rows whose `name` is still the `UNTITLED_PROJECT_NAME` placeholder, and
`create_project@1` refuses that literal title, so a project a human named can never be
auto-renamed.

### Directory read — `GET /api/v1/projects`

`GET /api/v1/projects?status=active|archived&limit=&cursor=` requires `project.read`.
`status` defaults to `active`; `limit` defaults to 50 and is constrained to 1–100; `cursor` is
the opaque keyset cursor from `meta.next_cursor`. Only `kind = 'marketing'` rows of the
authenticated workspace are served, and `draft` rows are never served. Order is
`pinned DESC, updated_at DESC, project_id DESC` over the composite `updated_at`; the cursor
carries all three parts, so a project that is pinned (or whose newest conversation moves) between
two pages still pages deterministically. A foreign or malformed cursor is `422 INVALID_CURSOR`.

```json
{
  "data": [
    {
      "id": "prj_01J...",
      "title": "Q4 enterprise push",
      "description": "",
      "href": "/projects/prj_01J...",
      "status": "active",
      "pinned": true,
      "brand_id": "brand_01J...",
      "product_id": null,
      "created_at": "2026-09-19T12:00:00Z",
      "updated_at": "2026-09-19T12:30:00Z",
      "archived_at": null,
      "activity": { "chats": 4, "running": 1, "needs_input": 0 }
    }
  ],
  "meta": { "next_cursor": null }
}
```

`status` is exactly `"active" | "archived"`. `archived_at` is non-null if and only if
`status = "archived"` (a durable CHECK). `activity` is counted, never guessed: `chats` is the
project's active thread count, and `running` / `needs_input` come from the same whole-page
`threads_running` and `open_gate_kinds_for_threads` batch reads the sidebar already uses — two
queries for the page, not two per card. The same item shape is the response body of all three
write routes below.

The frontend walks the cursor once on screen load (projects are tens, not thousands) and keeps
the dummy's client-side search, sort and 12-per-page paging.

### Directory writes

All three require `project.write`, dispatch through the journaled toolbelt, and return
`{ "data": <directory item> }`. The four tools behind them — `create_project@1`,
`update_project_details@1`, `set_project_pinned@1`, `set_project_archived@1` — are
`ToolEffectClass.WRITE` and **granted to no agent role**: they are human-only through this HTTP
boundary. (An agent that could archive a project could hide its own work.) Each resolves the
project workspace-scoped and refuses `project_not_found` for a foreign or missing id.

**`POST /api/v1/projects/blank`** → `201 { "data": <directory item> }`.

```json
{ "brand_id": "brand_01J...", "title": "Q4 enterprise push", "description": "" }
```

`title` is trimmed, 1–200 characters; `description` is ≤2000 characters and defaults to `""`.
**`Idempotency-Key` is required** (the Home-bootstrap rule): the project id is derived from it, so
a retried create returns the same project instead of a second one. A missing or blank header is
`400 IDEMPOTENCY_KEY_REQUIRED`. A brand outside the workspace is `404 BRAND_NOT_FOUND`; the
reserved untitled placeholder as a title is `422 PROJECT_TITLE_RESERVED`. The project is born
`active`, `kind = 'marketing'`, with zero threads. No brand picker is exposed — the frontend
chooses the brand the way Home does.

**`PATCH /api/v1/projects/:projectId`** `{ "title"?, "description"?, "pinned"? }` →
`200 { "data": <directory item> }`. At least one field is required (`422` otherwise); `title`
1–200 trimmed, `description` ≤2000, `pinned` boolean. The route **dispatches and decides
nothing**: any label edit — title, objective, or both — is one `update_project_details@1` call,
and `pinned` is always its own `set_project_pinned@1` call. They cannot share one call, because
pinning an archived project is allowed and relabelling one is not. When the body carries only one
label, the other is supplied from the current directory row, so a title-only edit keeps the
objective the human wrote. Relabelling an archived project is `409 PROJECT_ARCHIVED`.

> Spec deviation: the spec routed a title-only PATCH to `rename_project@1`. As built, this
> surface never calls `rename_project@1` for any body; the tool stays registered for replay and
> for this file's contract history, and thread rename is unaffected.

**`POST /api/v1/projects/:projectId/archive`** `{ "archived": true|false }` →
`200 { "data": <directory item> }`. Reversible, and never a delete. Archiving is refused
`409 PROJECT_RUNNING` while any active thread of the project has running work ("This project has
running work. Wait for it to finish before archiving." — the message carries no count, unlike the
spec's sketch); a **restore never asks that question**, so a project cannot be trapped in the
archive by work it started before. A `draft` project is `409 PROJECT_DRAFT`. Archived projects
leave the sidebar entirely and are read-only on the home; `create_thread@1` refuses a new chat in
one with `project_archived`.

`Idempotency-Key` is optional on PATCH and archive (the chat-tool convention); PATCH suffixes the
key per dispatched tool (`…:details`, `…:pinned`) so the two mutations never collide.

> Spec deviation: `create_project@1` ships `ReplayPolicy.DOMAIN_IDEMPOTENT` with durable identity
> `project(project_id, workspace_id)`, not the spec's `OPERATION_IDEMPOTENT` /
> `project(project_id)`. The id is still derived from the Idempotency-Key, so the retry guarantee
> the route advertises is unchanged.

### Sidebar and shell additions

`GET /api/v1/projects/sidebar` now serves **`pinned` and `updated_at` on each project** and orders
`pinned DESC, updated_at DESC, project_id DESC` over the same composite `updated_at` as the
directory — the rail and the directory show the same workspace and may never disagree about which
project is on top. Its cursor is now `(pinned, updated_at, project_id)`. It keeps serving only
`kind = 'marketing'`, `status = 'active'` rows. This supersedes §5's line "Project-level `pinned`
is absent because no project-pin mutation exists"; the frontend wire transform no longer
hard-codes `pinned: false`.

```json
{
  "id": "prj_01J...",
  "title": "Q4 enterprise push",
  "href": "/projects/prj_01J...",
  "pinned": true,
  "updated_at": "2026-09-19T12:30:00Z",
  "conversations": [ /* unchanged */ ]
}
```

`GET /api/v1/projects/:projectId` (the shell, §5) adds `description` (`""` when unset), `pinned`,
`updated_at` and `archived_at` to the wire. It does **not** expose `kind`; a system project is
`404 PROJECT_NOT_FOUND` here instead, which is what the spec's "system projects 404 here as
everywhere" line means in practice. *Recent chats* on the home is the existing
`GET /api/v1/projects/:projectId/threads`, unchanged.

### Instructions — `/frontend/v1/projects/{id}/instructions`

The home's Instructions panel is one project document and nothing more:
`project/instructions.md` in the project's own document chain. Storing it there rather than in a
column is the point — the agent already reads this project's documents in its mounted workspace,
so instructions a human types are context the next turn has, with no second mechanism carrying
them. These two routes live on the `/frontend/v1` app (browser path
`/api/clue/frontend/v1/…`), not the chat router.

**`GET /frontend/v1/projects/{id}/instructions`** — scoped by the authenticated session's
workspace, as every `/frontend/v1` read is (the writes below additionally require
`project.write`):

```json
{ "data": { "body": "Always lead with the security angle.", "revision": 3,
            "updated_at": "2026-09-19T12:30:00Z" } }
```

`data: null` is the honest empty panel — this project has never had instructions. A deployment
with no artifact storage also reads `null` (nothing was ever stored there), while the PUT below
refuses loudly.

**`PUT /frontend/v1/projects/{id}/instructions`** (`project.write`)
`{ "body": "…", "expected_revision": 3 | null }` → the same response shape. `body` is ≤12,000
characters. The wire names a **revision, never a document id**: the panel holds the version it
last read and sends it back with the next save. `expected_revision: null` means "there were none
when I opened this" and creates version 1; an integer (≥1) means "I typed over this version" and
appends the next one. Either request that disagrees with what is at rest is
`409 DOCUMENT_REVISION_CONFLICT` — the same answer the documents PUT gives, because it is the same
event: someone wrote first. Other refusals: `404 PROJECT_NOT_FOUND` (foreign, missing, or system),
`409 PROJECT_ARCHIVED`, `422 PROJECT_DOCUMENT_BODY_EMPTY`, `503 KNOWLEDGE_STORAGE_UNAVAILABLE`
(this process composed no artifact storage), `401 UNAUTHORIZED`.

A successful save bumps `project.updated_at` inside the write's own transaction (a refused save
never moves the project's row) and then, **after the commit**, refreshes the project library so
the version the human just saved is the one the agent's mounted workspace serves on the next turn.

`project/instructions.md` is excluded from the **project documents list**
(`GET /frontend/v1/projects/{id}/documents`) — it is a real document of the project and is still
served by id, but the home draws it in its own panel and a second card for it in that feed is a
surface the design never drew. The exclusion is at the list composition only, so the agent's
project-library tree still contains the file.

Not decided here: whether instructions ride the opening-context envelope every turn. They do not
today (the opening cards run an 8 KiB budget against a 12,000-character cap); that is a recorded
context-budget follow-up.

### Memory — `/frontend/v1/projects/{id}/memory`

The home's Memory panel is **not** a notes table this surface owns. Every note a human types goes
through the scoped-memory write seam (Doc M), so it is reconciled against what is already
remembered, born with the trust its provenance earns, journaled and capped — exactly like a note
the agent distils from a conversation. There is one write path into memory and this is it.

Notes are submitted as `scope = project`, `type = preference`,
`provenance_class = user_stated`, `trigger = "project_home_note"`. All four routes are
`(workspace, project)`-scoped; every write requires `project.write` and refuses
`409 PROJECT_ARCHIVED` on an archived project.

**`GET /frontend/v1/projects/{id}/memory`** (workspace-scoped, like every `/frontend/v1` read)
→ `{ "data": [ … ] }` — **active, `user_stated`, project-scope memories only**, newest first:

```json
{ "id": "mem_01J...", "text": "Prefer case studies over feature lists.",
  "source_thread_id": "thr_01J...", "source_thread_title": "Northstar outreach",
  "created_at": "2026-09-19T12:30:00Z" }
```

The list is deliberately narrower than the store's filter: an agent-observed record and a
superseded one are real memories the agent still reasons over, but they are not this human's list
of notes, and showing them would invite a human to "delete" something they never wrote.
`source_thread_title` is joined from `agent_thread` at read time rather than copied onto the
memory, so a renamed thread never leaves the panel quoting a title that no longer exists; a null
title renders the frontend's "New chat" label.

**`POST /frontend/v1/projects/{id}/memory`** (`project.write`)
`{ "text": "…", "source_thread_id": null }` → `201`:

```json
{ "data": { /* the note */ }, "verdict": "add" }
```

`text` is 1–4000 characters. `verdict` is the reconciliation outcome —
`add | update | supersede | noop` — carried because "we already knew that" is a different outcome
from "noted" (a `noop` returns the surviving twin). The UI does not render it today.

**`PUT /frontend/v1/projects/{id}/memory/{memory_id}`** (`project.write`), same body, → `200` with
the same shape. The substrate is append-only, so **an edit is a retire plus a submit, not an
update**: the successor carries a new id and the old record keeps its trail. Both happen in **one
transaction** — a refused submit rolls the retire back and the note the human was editing survives
intact, so the dialog's Save behaves exactly as drawn.

**`DELETE /frontend/v1/projects/{id}/memory/{memory_id}`** (`project.write`) → `204`. Removal
**invalidates** the record (journaled, never deleted), so a repeat click is a `404` rather than a
second write.

Refusals, all in the shared `{"error": {"code", "message", "requestId"}}` envelope:

| HTTP | `error.code` | Meaning |
|---|---|---|
| 409 | `MEMORY_DISABLED` | Memory is off for this workspace. **On the read too** — a panel that drew nothing would say "no notes" when the truth is "nothing is being kept". |
| 422 | `MEMORY_REJECTED` | The seam refused the note: fact-shaped (facts belong in the claim store; memory holds only advisory preferences and learnings) or a body rule (verbatim personal content without a resolved subject). The seam's own words are the `message`, and the frontend renders them verbatim in the dialog's existing error slot. |
| 503 | `MEMORY_UNAVAILABLE` | This deployment composed no model gateway, so there is no reconcile judge. The two submitting writes (POST, PUT) refuse; the list and DELETE still serve. |
| 404 | `MEMORY_NOT_FOUND` | The note is not this project's, not `user_stated`, or is no longer active. A repeat removal is this, not a second write. |
| 422 | `MEMORY_SOURCE_NOT_IN_PROJECT` | `source_thread_id` is not a thread of this project. |
| 404 | `PROJECT_NOT_FOUND` | Foreign, missing, or a system project. |
| 409 | `PROJECT_ARCHIVED` | Writes only. |

> Spec deviation: the spec's §4 sketched `MEMORY_REJECTED` as `422 {reason, detail}`. As built the
> envelope is the shared `{code, message}` one — the seam's detail is the `message`, and no
> separate `reason` field rides the wire.

An accepted write bumps `project.updated_at` in the write's own transaction, so a refused note
never moves the project's row.

**Deployment precondition.** These routes need `CLUE_MEMORY_ENABLED=true` for the workspace (the
`.env.example` default is `false`), `CLUE_MEMORY_RECONCILE_MODEL` set, and a real gateway key:
**every human note costs one reconcile-judge model call.** `.env.example` carries that note beside
the flag.

### Error codes this integration adds

| HTTP | `error.code` | Where |
|---|---|---|
| 400 | `IDEMPOTENCY_KEY_REQUIRED` | `POST /api/v1/projects/blank` with no usable header. |
| 404 | `PROJECT_NOT_FOUND` | Every project route: foreign, missing, `draft` (on directory-lensed reads), or `kind = 'system'`. |
| 404 | `BRAND_NOT_FOUND` | Create, for a brand outside the workspace. |
| 409 | `PROJECT_ARCHIVED` | Details edit, instructions save, memory write, new thread. |
| 409 | `PROJECT_RUNNING` | Archive, while a thread of the project is running. |
| 409 | `PROJECT_DRAFT` | Archive, on a `draft` project. |
| 409 | `DOCUMENT_REVISION_CONFLICT` | Instructions PUT, on any disagreement with what is at rest. |
| 409 | `MEMORY_DISABLED` | Every memory route, read included. |
| 422 | `PROJECT_TITLE_RESERVED` | Create, with the untitled placeholder as the title. |
| 422 | `INVALID_CURSOR` | Directory and sidebar paging. |
| 422 | `MEMORY_REJECTED` / `MEMORY_SOURCE_NOT_IN_PROJECT` | Memory writes. |
| 422 | `PROJECT_DOCUMENT_BODY_EMPTY` | Instructions PUT. |
| 503 | `MEMORY_UNAVAILABLE` / `KNOWLEDGE_STORAGE_UNAVAILABLE` | A deployment with no gateway / no artifact storage. |

Schema failures stay `422`. The frontend keeps the dialog draft on any failure and shows the
`message`; out-of-dialog failures use the directory's dismissible error bar.

### What this integration deliberately does not add

Project deletion; an aggregate `GET /projects/directory`; a client command bus or localStorage
project store; a brand picker; agent-observed memory review; in-place memory editing; memory types
other than `preference`; automatic memory extraction from chats; a bulk "archive all chats"
endpoint; any agent-role grant for the four project tools; and any new visible control, label or
caption for backend concepts the design did not draw.

## As-built thread-shell contract — founder-ratified 2026-08-08 (Lane D D0–D2)

**This section is authoritative over the historical proposal above and subordinate only to the
2026-08-10 executable integration contract.** It records the founder's ratification of the nine
as-built deviations from Lane D slice D0 (the durable thread shell) plus the D2 turn-submission
contract. Owner: Lane D
(`docs/specs/FI-lane-D-production-chat-and-launch.md`); implementation in
`platform/api/clue_api/chat/` behind `CLUE_CHAT_ENABLED` (default off).

1. **Rename/pin are per-thread.** `PATCH /api/v1/projects/:projectId/threads/:threadId`
   `{title?, pinned?}` → `200` with the updated thread. The proposal's
   `PATCH /projects/:projectId` (project rename/pin) mutates the project table, which is outside
   the chat shell's ownership; it stays unimplemented here.
2. **Archive is per-thread.** `POST …/threads/:threadId/archive` → `200` with the updated
   thread. Archive is a reversible status flip, so the response says what happened; the
   proposal's bulk archive-all endpoint does not exist.
3. **`GET /api/v1/projects/:projectId/threads`** — first-class paginated thread list
   (the embedded sidebar payloads remain for composite views).
4. **Cursor pagination everywhere.** List endpoints take `?limit`/`?cursor`; responses carry
   `meta.next_cursor`. Cursors are keyset (stable under concurrent inserts), backed by
   composite indexes.
5. **Thread `status` is `idle | archived` today.** The proposal's richer vocabulary
   (`running | review | approval | needs-input`) is *derived* state — latest turn status + open
   gates — and lights up with slices D3/D4. Single change point:
   `platform/api/clue_api/chat/schemas.py::thread_status`.
6. **Create returns `201` with a superset:** `{id, title, href, status, pinned, project_id,
   created_at, updated_at}`.
7. **`title` is optional on create** (an unnamed thread is `title: null`); a blank/whitespace
   title is refused.
8. **Message reads are body-free.** The paginated message list returns role, sequence,
   `body_artifact_key`, `body_sha256`, and typed `refs[]` (closed flavor vocabulary:
   `attachment, output, open_gate, next_action, assumption, workspace_output`). Bodies hydrate
   through the D3 rehydration read and stream live via SSE — never inline in list responses.
9. **Not implemented in the thread shell (deliberate):** `POST /projects`,
   `DELETE /projects/:projectId` (project lifecycle — phase-2 / separate owner), the proposal's
   `POST …/threads/:threadId/messages` (**superseded** by the turn endpoint below), and the
   runs/artifacts endpoints (phase-2, gated on the design-integration branch merge).

**The turn endpoint (D2, replaces `POST …/messages`):**
`POST /api/v1/projects/:projectId/threads/:threadId/turns` accepts exactly one of an ordinary
`{message}` or (from D4) a structured `gate_response`; plus idempotency identity. It persists the
user message + an immutable `agent_turn_submission` receipt (real authenticated principal
identity; never client-supplied `actor_id`/`action_ref`) **before** enqueueing detached
execution, and returns `202 {data:{turn_id}}`. Duplicate submission under one idempotency
identity returns the same turn. A queued-not-yet-executing turn is visible as a submission;
read surfaces union submissions with turn events (founder-acked two-phase turn identity,
2026-08-08). Streaming/live transcript arrives via the D3 SSE contract
(charter §§3.1–3.6); `GET …/runs/:runId` polling in the proposal is superseded by that stream
for chat-visible progress.

### Gallery leg-derived design-artifact feed (2026-08-18, ratified)

**Endpoint:** `GET /api/v1/projects/{project_id}/design-artifacts` — the per-project gallery's
list read, sibling of the W1.3 single-artifact resolver and sharing its exact auth/scoping
posture (workspace fail-closed on both the leg and document sides; unknown or foreign-workspace
project → 404 `PROJECT_NOT_FOUND`).

**Semantics (leg-derived v1, founder-ratified 2026-08-18):** the project's documents are the
DISTINCT non-null `document_id`s of `design_leg` rows whose thread belongs to the project
(`design_leg JOIN agent_thread`), restricted to the caller's workspace and `doc_kind = 'web'`
(scene/ad documents stay out until the ad-editor plan). Order: `updated_at DESC`. A document
with no leg belongs to no project and appears in no gallery — the ratified, accepted gap.
A workspace-wide listing was considered and REJECTED (it would show every project's documents
in every gallery).

**Wire:** `{data: [{id, project_id, document_id, kind, title, status, current_version_id,
created_at, updated_at, origin_thread_id}]}` — the W1.3 item shape plus three fields;
`origin_thread_id` is the document's latest leg's thread. In the v1 seam `id == document_id`.

This supersedes the R3/R7-era `artifacts: []` posture for the project gallery: the artifact
route now feeds the gallery real cards through `DesignArtifactRepository.list(projectId)`
(fixture + HTTP adapters) and the pure `toProjectArtifact` mapper. ~~Cards carry no thumbnail
(`imagePath` optional — ruling 2: the frame renders without artwork; no placeholder imagery)~~
**[SUPERSEDED 2026-08-31 — cards carry REAL artwork: `toProjectArtifact` now composes
`imagePath` from the versioned thumbnail route, for both kinds. The empty frame survives as
the FALLBACK (a failed load), not the universal state. See "Design-document thumbnails
(2026-08-31)" below.]** Cards still carry no fabricated account attribution (unattributed
artifacts show no account badge).

**Two durable contract rules (recorded by founder order):**
1. **Every future artifact-creation surface MUST write project linkage at creation time** —
   the gallery's "create a new artifact" affordance, Duplicate, and any non-agent path must
   open/write a `design_leg` (or the registry linkage that replaces it) binding the document
   to the project, or the artifact will appear in no gallery.
2. **This read is replaced WHOLESALE when the real platform-artifact registry lands**
   (documents registered as platform artifacts with first-class project linkage). No
   incremental migration of the leg-derived query.

#### Kind-aware feed — resolved contract (2026-08-20, AD2.1)

**Supersedes the `doc_kind = 'web'` restriction above.** The feed now serves **every** doc
kind a leg names, and `kind` on the wire is real rather than constant: a `web` document
reports `kind: "web"`, a `scene` document reports `kind: "ad"` — the same expression the
single-artifact read (`GET …/design-artifacts/{artifact_id}`) already applied. The old filter
made the chats route structurally unable to reach an ad artifact (audit finding F1): the
document existed, the leg named it, and the gallery dropped it. Nothing else about the read
changed — the wire shape, the ordering (`updated_at DESC`), the workspace fail-closed posture,
and the leg-derived project binding are untouched, and `doc_kind` itself is never leaked.

**[AMENDED 2026-08-23 — ads can now be CHAT-BORN.** Founder genad ruling 1 reverses the v1
"a design leg cannot create a scene document" refusal: `open_design_leg@3` births a scene
document at a ratified format, brand-stamped, the way `@2` already births web ones. So a
`kind: "ad"` card appears in this feed **at leg-open**, before any generation turn has run —
not only for editor-seeded documents. The read itself is unchanged (the leg names the new
document at birth, satisfying durable contract rule 1 above). Plan:
`docs/superpowers/plans/2026-08-23-chat-driven-ad-creation.md`.]**

**[AMENDED AGAIN 2026-08-23 (evening) — the birth carries NO format.** Founder genad2
ruling 1 supersedes the format half of the note above: `open_design_leg@**4**` births a
**zero-page** scene document (`pages == {}`) with **no format or dimension parameters** —
`ad_format`/`ad_width`/`ad_height` are gone from the tool's input model, and the platform
page-minter (`AD_FORMAT_PRESETS`/`ad_birth_page`/`mint_empty_ad_document`) is deleted. The
**design agent authors the page itself** — size, unit (px for digital, mm/in for print) and
layout come from the user's own words. Unchanged: the birth is still one transaction with
the leg insert, still brand-stamped, still pinned at `document_version_guard=0`, and a
`kind: "ad"` card still appears in this feed at leg-open. The one wire consequence: a
newborn ad has no page, so `document_page_pixels` is honestly `null` and the card's
dimensions are absent until the agent's first generation turn persists a page (the
frontend renders the pageless state rather than fabricating a size). Plan:
`docs/superpowers/plans/2026-08-23-agent-authored-pages.md`.]**

**Resolved frontend mapping (`toProjectArtifact`):**

| wire `kind` | `type` | `collateralType` | `imagePath` |
| --- | --- | --- | --- |
| `"web"` | `"website"` | `"microsite"` | absent — **superseded 2026-08-31, see below** |
| `"ad"` | `"canvas"` | **absent** | absent — **superseded 2026-08-31, see below** |

- `type: "canvas"` is what carries the ad into the editor with **zero mount changes** — both
  mounts reconstruct the artifact kind as `source.type === "website" ? "web" : "ad"`.
- `collateralType` is **omitted** for ads, not guessed. The document knows it is an ad; it does
  not know which channel, and `linkedin-ad` / `meta-ad` are channel claims. Note the
  consequence, unchanged by this task: the gallery's own `normalizeGalleryArtifact` still
  defaults an absent collateral type on a `canvas` artifact to `linkedin-ad` (its
  dummy-era fallback), so an ad card currently *labels* as "LinkedIn ad" and groups under
  "Ads". Honest channel labelling for real ad documents needs a founder ruling on the
  vocabulary and is deliberately out of AD2.1's scope.
- ~~**No thumbnail** — ruling 2 holds for ads exactly as for websites: the card frame renders
  empty rather than showing placeholder artwork (the ratified honest empty card).~~
  **[SUPERSEDED 2026-08-31 — design documents have real thumbnails now; see the next
  section. The empty frame survives as the FALLBACK, not the universal state.]** `size`
  falls to the gallery's `square` 1080×1080 default for canvas artifacts that have no page.

### Design-document thumbnails (2026-08-31)

`GET /api/clue/design/documents/{documentId}/thumbnail?v={currentVersionId}` →
`200 image/png`. Lazily generated server-side on first read (web: Chromium
screenshot of the render HTML at 1448×1086 → 724×543; ad/scene: engine Skia
PNG of page 1, max edge 724) and cached by `(document, version)` in the design
blob store. `v` equal to the document's current version ⇒
`Cache-Control: private, max-age=31536000, immutable`; any other `v` serves the
current bytes with `no-store`. Generation failure is a typed 502
(`thumbnail.*`); the gallery card's empty preview frame is the fallback.
The four codes are `thumbnail.tailwind_runtime_missing` (no Tailwind browser
runtime for the web capture), `thumbnail.capture_failed` (Playwright/Chromium
missing or the screenshot itself failed), and a **kind-aware split of the engine
`CoreError`** — `thumbnail.render_failed` on a web document (the failing step is
the render; the web branch never exports) and `thumbnail.export_failed` on a
scene (the engine PNG export).
The frontend composes this URL in `toProjectArtifact` from the list read's
`documentId` + `currentVersionId` — no wire-shape change.

**Notes from the 2026-08-31 live browser walk** (evidence in
`_memory/2026-08-31-gallery-card-thumbnails.md`):

- Both card `Image`s are `unoptimized`, so the browser fetches the URL directly and the
  BFF's session cookie rides along; Next's optimizer would strip it and 401.
- A failed load falls back through `onError`, so a 502 shows the ruled empty frame — not
  a broken-image glyph — and the rest of the gallery is unaffected. A 200 carrying a
  *wrong* body cannot trip that fallback; correctness of the artwork is a server concern.
- Generation happens on the READ path only. An inspector write bumps `currentVersionId`,
  which changes the URL; the new version's PNG is produced by the next gallery read, so
  the editor's edit round-trip is untouched.
- Superseded-version rows and blobs are kept (no pruning) — a deliberate follow-up, not a
  leak: the index is `(workspace, document, version)`.
- `etag` is not in the BFF's forwarded response headers, so revalidation does not survive
  the proxy. Harmless under the immutable `?v=` scheme — do not design against it.

### Research progress card (2026-09-12)

Spec `docs/superpowers/specs/archive/2026-09-12-research-progress-card-design.md`. One pinned card per
project above the composer, rendered from `GET /frontend/v1/projects/:projectId/research/progress`
(BFF `GET /api/projects/:projectId/research-progress`): `{ requested_accounts, queued, running,
finished, progress_pct, pill, last_finished_at, agents[{account_name, stage, subject}],
attention[{account_name, reason}] } | null`.

**Researcher-owned flow (2026-09-28).** Agent rows optionally carry `subject_name` for a contact.
Stages are `researching` → `compiling_findings` → `storing_claims` → `writing_narrative` →
`completed`, derived from recorded tool activity, committed JSON dossier snapshots and published
page pointers. Older flows retain `deep_research` → `synthesis` → `committee` → `member_research`.
New-flow percentages represent completed milestones (0/25/50/75/100), not elapsed-time estimates;
an account's share averages its own work and all nominated person jobs.

Product completion means required outputs are published: both account Overview and Insights,
or the person's Contact page, in the same workspace/project/context/run, with available artifacts
and a completed latest dossier where indexed. A `needs_review` execution with these outputs shows
**Completed**; execution status and diagnostic records are unchanged. Missing required pages do
not qualify. Account list/detail status uses the same publication projection; people still running
remain visible in the project progress card. Reads are batched, not one query per account.

Completed cards linger 60 seconds from delivery. Frontend polls every 5 seconds while a card is
served and rotates the status line every 4 seconds (`model/research-progress-line.ts`). No chevron,
no dismiss, no per-account detail. Field mapping and multiple-project navigation are unchanged.

**Provider incidents on the card (2026-09-16).** Spec
`docs/superpowers/specs/archive/2026-09-16-provider-incidents-design.md`. The payload carries one more
field:

```
incident: { provider_label, reason_label, since, affected, notified } | null
```

the open provider incident behind a `needs_attention` card, else `null`. `provider_label` and
`reason_label` are served words, not codes (`"Model provider"`, `"key limit exceeded"` — the tables
are `clue_api.provider_incidents.provider_display` / `reason_words`); `since` is the incident's
`opened_at` as a `Z`-suffixed ISO timestamp; `affected` is its failure count; `notified` is true
only when a Sentry event for the open actually left the box. The incident is looked up for the
provider named by the most recently finished job whose `failure_code` parses, so a card without a
provider-coded failure keeps `incident: null`. An `attention[].reason` may therefore be a **full
sentence** ending `"Clue has been notified."` rather than the short phrase the card used before —
only rows this incident wrote are rewritten, so the frontend must render `reason` as served and
never parse it.

**Failed-turn codes (2026-09-16).** A turn refused or broken by a provider fails with
`provider_refused:<provider>:<reason>` (a decision no retry changes — credits exhausted, key limit,
invalid key, suspended account) or `provider_failed:<provider>:<reason>` (a fault that usually
passes — rate limited, server errors, timeouts). Both render as sentences through
`designTurnFailureNotice` (`features/projects/model/design-leg.ts`), which mirrors the same two
label tables; a provider or reason the tables do not know renders as itself. Turn rows written
before this plan keep their old codes (`model_error`, `permission_denied_error`) and render exactly
as they did.

### Project documents — the plan and the project's own knowledge (2026-09-12)

Spec `docs/superpowers/specs/archive/2026-09-12-project-context-and-icp-authoring-design.md` §4.3. A
project owns documents of its own — the plan the Head of ABM writes (`write_project_document@1` →
`project/plan.md`), and any ICP or persona document authored local to the project. They are served
by three routes on the workspace-scoped `/frontend/v1` router
(`platform/api/clue_api/frontend_read/project_documents.py`), registered after the research-progress
route. Wire is **snake_case** in a `{ "data": … }` envelope — the `discovery/current` and
`research/progress` neighbours' shape, not the camelCase `WireModel` the accounts contract uses.
Timestamps are `Z`-suffixed ISO. In the authenticated application, the shared backend client
proves the provider session, resolves Clue membership and stamps `X-Clue-Workspace-Id`.
The router's legacy `X-Workspace-Id` dependency is overridden by authenticated composition;
the frontend never supplies a static workspace or trusts a browser-supplied workspace header.

| route | answer |
| --- | --- |
| `GET /frontend/v1/projects/:projectId/documents` | `{ data: { documents: Doc[] } }` |
| `GET /frontend/v1/projects/:projectId/documents/:documentId` | `{ data: DocDetail }` |
| `PUT /frontend/v1/projects/:projectId/documents/:documentId` | `{ data: DocDetail }` |

```
Doc        = { id, path, kind, title, version, status, updated_at, icp_key }   // icp_key: string | null
DocDetail  = Doc & { markdown, front_matter }
PUT body   = { body: string (1…1_000_000), expected_revision: int ≥ 1 }
```

- **Scope is the store's, not a check re-applied at the route.** Every read and write is
  `(workspace, project)`-keyed, so another project's — or another tenant's — document is *absent*,
  never refused differently; a probe cannot tell "not yours" from "not there".
- **`kind` is an open string, not an enum** (founder ruling 2026-09-14, free-flowing documents):
  the agent writes any markdown document under `project/` and names its kind in the document's
  own front matter; the backend serves that word as is (`campaign-plan`, `competitive-brief`, …
  beside `project-plan`, `icp-definition`, `audience-persona`). The frontend validates `kind` as
  a non-empty string and labels the three it knows; any other kind is labelled by its own words
  (`documentKindLabel`). Amended 2026-09-15: the earlier three-value enum failed the whole
  document list — and so the Gallery — the first time the agent wrote a fourth kind.
- **`title` is the one composed value**: `kind = "project-plan"` → `"Plan"`;
  `kind = "audience-persona"` → `` `Personas — ${icp_key}` ``; everything else is titled by its own
  text (front-matter `title`, else its first heading) through the same rule the ICP gate uses. A
  document whose blob cannot be read is still listed, named by its file path.
- **The PUT is the Knowledge editor's contract.** `expected_revision` is the version the human typed
  over; a successful save mints the **next immutable version** (`status: "ready"` for a plan) with
  `user_edit` provenance in `front_matter` (`source_document_id`, `source_version`, the saver) and
  retires the predecessor. An identical body is a no-op returning the same row. Auth: an
  authenticated principal with `project.write`, else `local-development-user` when the router allows
  local mutations, else `401 UNAUTHORIZED`.
- **Errors** (`{ detail: { code, message } }`): `404 PROJECT_DOCUMENT_NOT_FOUND` (absent, or not this
  project's), `409 DOCUMENT_REVISION_CONFLICT` (stale `expected_revision`, or a concurrent version
  race — someone else wrote first; re-read and re-apply), `422 DOCUMENT_BODY_EMPTY`,
  `503 KNOWLEDGE_STORAGE_UNAVAILABLE` (detail GET and PUT, when the process has no blob storage).
- **CORS on this router is `["GET", "OPTIONS"]`**, so the PUT is same-origin/BFF-only — exactly like
  the brand-knowledge PUT. The Plan tab reaches it through the BFF, not the browser.
- **The chat side:** a finalize carrying `{ object_type: "project_document", object_id, version }`
  in `domain_refs` projects one `PLAN` part titled `"Plan"` with `revision_label` `v{version}`, and
  the tool reads as **"Write the project plan"** in the transcript.
- **Frontend connection implemented (Lane 2 Task 4, 2026-09-13):**
  `features/projects/model/project-documents.ts` validates lists/details and maps `updated_at`,
  `icp_key` and `front_matter` to camelCase. Kinds are the three frozen project-document kinds;
  status and nullable ICP keys are retained without guesses. The plan is selected by exact path
  `project/plan.md`. Edited labels use the viewer's local timezone and an explicit clock.
- Server reads use `listProjectDocuments` / `getProjectDocument` in
  `data/project-documents.repository.ts`, through the shared authenticated `fetchRead` client.
  There is no fixture fallback, and failed reads never become empty document lists.
- Browser routes are `GET /api/projects/:projectId/documents` and
  `GET|PUT /api/projects/:projectId/documents/:documentId`. All responses are `no-store`.
  PUT accepts **only** `{ body, expectedRevision }`, enforces the shared allowed-origin policy,
  and forwards `{ body, expected_revision }` with session-derived credentials. Invalid JSON is
  400; invalid/nonpositive revision, blank/oversized body or extra fields are 422. Backend
  statuses/bodies (including 401/403/404/409) pass through, with request IDs retained.
- `saveProjectDocument` lives in **`data/project-document-actions.ts`**, keeping browser imports
  free of the server-only read/authentication graph, as the Knowledge actions already do.
  It sends the original Markdown unchanged, never sends front matter, and returns the full saved
  detail, including the **new ID/version** (or unchanged ones for a no-op). Callers must use that
  returned base for the next save. Saves are not retried or merged automatically.
- Repository/action errors retain `ClueApiError.status`, `code` and `requestId`. A 409 explains
  that a newer **document** exists and advises keeping/copying the draft before loading it;
  401/403 explain missing view/edit permission. Both `{ error: … }` and FastAPI `{ detail: … }`
  refusal envelopes are understood for saves. These functions do not own or clear editor drafts.
- **Plan pane implemented (Lane 2 Tasks 6–7, 2026-09-14):** `?surface=plan` opens the
  third project rail tab with the approved empty state or the current `project/plan.md`.
  It carries no artifact edit/selection parameters. Browser reads use validated same-origin
  queries with abortable requests, no fixture fallback and explicit failure states.
- Plan and Knowledge share `useVersionedMarkdownEditor` and its pure session transitions.
  Drafts are keyed by workspace/project/path; tab switches keep the mounted editor. Opening is
  clean; Save adopts the returned immutable ID/version; Discard resets to the newest loaded
  document. Dirty drafts retain their original base across external refreshes. A failed or
  conflicting save retains the draft and offers a latest-version check. Source parse errors,
  missing `project.write` permission and blank project bodies disable saving.
- Project-document plan-card titles open Plan. Newly received plan parts with
  `planRef.objectType === "project_document"` open and refresh it once. The chat controller
  seeds `ProjectPlanWriteTracker` with each turn's initial `lastEventId` from the server.
  Backlog parts at or before that cursor are rendered without opening Plan, even when they arrive
  after `loading` becomes false. Later parts announce a write once per document part ID. Cursors
  survive reconnects without advancing on subsequent reads, so missed live writes still count.
  Newly submitted turns start at zero. The shell consumes `planWriteRevision`; it does not infer
  freshness from transcript rendering, client timestamps, or a tool name.
- Live Semarang verification: empty/read states, clean Edit, tab-switch draft retention and two
  browser saves, with new IDs/versions verified in Postgres/artifact storage. After sign-in was
  restored, full reload preserved saved content; a stale browser save kept its draft; checking
  for updates preserved it; Discard adopted the newer version and the next save succeeded.
  Arrow/Home/End tab navigation passed. Preview and Edit at 720 px and 390 px contained long
  inline/code-block text without widening the page. Controlled, held backend streams verified
  Plan-card clicks, new-write auto-open, duplicate delivery, and cold backlog replay. No provider
  or fleet execution was used. The fixture is archived with its append-only audit records retained.
- **Named file tabs and Gallery documents (Task 8, founder amendment 2026-09-14):**
  the fixed Plan tab above is superseded. Gallery and Target accounts remain navigation;
  document tabs exist only after an explicit Gallery/card click, direct document link, or
  fresh agent write. All three Markdown kinds appear as Documents cards, alongside designs.
  The file tab/header uses the backend title, never a fabricated design artifact. Existing
  backend Plan/persona title rules remain unchanged; this slice does not introduce rename.
- A shared browser list hook supplies Gallery and the mounted document surfaces. A card
  opens its stable path using `?surface=plan&document=<path>`. A transcript reference resolves
  its immutable ID through the repository to a path, then loads the current listed version.
  Old `?surface=plan` links still select `project/plan.md`. No artifact identity param is added.
- Each opened Markdown file retains its own mounted editor session, even after closing its
  tab, until leaving the chat. Switching, closing and reopening preserve drafts and native
  undo. Closing the active last file returns to Gallery; closed files remain Gallery cards.
- Fresh persisted document references open the referenced file, not always the canonical plan.
  Cursor baselines and duplicate guards remain. Design feed IDs/update timestamps are baselined
  at mount; only new or changed files from the active chat auto-open, once per update.
- Scope stays with the existing three-kind Markdown API and design documents. Arbitrary file
  formats, dynamic backend kinds and document rename require a separate contract amendment.

### Scene editor canonical render context (2026-09-15, Task 40)

The existing `GET /api/clue/design/documents/{documentId}` scene response now adds a
read-only `render_context` beside `scene`. Web documents do not receive this field.
It contains `context_key`, `document_id`, `document_version`, `scene_brand_ref`,
`scene_medium`, `source`, full selected `brand_kit` JSON (or null), selected `mode`
(or null), and `diagnostics`. The context key hashes the complete selected inputs.
The document-store adapter validates the document/version identity and payload
shape; the shared Rust resolver validates token semantics and supported modes.

The API selects these inputs with the same helpers as normal export: an attached
kit takes precedence, followed by the scene's exact kit reference, then the normal
export fallback. Selection provenance remains explicit. If a selected kit differs
from a scene pin, the response carries a blocking diagnostic, including when an
unavailable pin led export to a fallback. No same-ID latest version is substituted
as an exact pin. Historical effective-brand metadata is not current selection
authority. This response does not persist a kit, rebind a document, or change its
version/history.

The platform WASM engine retains authored state separately from its resolved
presentation. Canonical token resolution and scene-medium normalization run before
layout on that presentation. Painting, hit testing, effective inspector spacing,
and all measurement passes consume the paired presentation; writes and undo keep
authored values and bindings. Optimistic/streamed frames carry their own paired
presentation, and document/context/revision fences discard stale font and
measurement completions. Missing, malformed, or unsupported context is visible
through diagnostics and does not claim canonical-ready geometry.

An explicit numeric gap edit now removes only its gap binding. A one-side padding
edit first materializes all four effective sides, then replaces the shared padding
binding, leaving sibling sides unchanged. Bound padding without a valid effective
tuple refuses the edit with a visible explanation. This intentionally replaces the
older token-preserving numeric-edit expectation: retaining the binding made a
successful-looking numeric edit ineffective. Unrelated bindings and authored undo
values remain intact.

This migration applies to the platform scene editor. The standalone editor retains
its legacy no-context engine behavior; its separate loader/UI is not migrated.
Equal spacing semantics do not establish pixel-identical text across browser and
server font engines; font/measurement diagnostics and rendered qualification remain
required.

## Chat attachments (2026-09-18)

Backend as built on branch `add-attachment` (spec `docs/superpowers/specs/archive/2026-09-18-chat-attachments-design.md`).
Every refusal below reaches the browser as the FI-1 error envelope
`{"error": {"code", "message", "requestId"}}` — the route raises
`HTTPException(detail={"code","message"})` and the projections app's middleware renders the envelope.

### Upload

- `POST /frontend/v1/uploads`, multipart field `file` → `201 {"data": {upload_id, filename,
  media_type, byte_count, artifact_key, sha256}}`. Workspace-scoped (`X-Workspace-Id`), requires
  `project.write`. Post `FormData` without a hand-set `Content-Type` so the browser writes the
  multipart boundary.
- Accepted types, in three families. **Text**: `text/markdown`, `text/plain`. **Image**:
  `image/png`, `image/jpeg`, `image/webp`, `image/gif`. **Document** (2026-09-19):
  `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
  (docx), `…presentationml.presentation` (pptx), `…spreadsheetml.sheet` (xlsx), `text/csv`,
  `application/json`. The declared content type is used only if it is one of those; otherwise the
  extension decides (`.md`/`.markdown`/`.txt`/`.png`/`.jpg`/`.jpeg`/`.webp`/`.gif`/`.pdf`/`.docx`/
  `.pptx`/`.xlsx`/`.csv`/`.json`).
- Refusals: `413 UPLOAD_TOO_LARGE`, `415 UPLOAD_UNSUPPORTED_TYPE`, `422 UPLOAD_NOT_UTF8` /
  `UPLOAD_NOT_AN_IMAGE` / `UPLOAD_NOT_A_DOCUMENT` / `UPLOAD_FILENAME_INVALID`,
  `503 STORAGE_UNAVAILABLE`. `UPLOAD_NOT_A_DOCUMENT` is the document family's content check: a PDF
  must begin `%PDF-`, a docx/pptx/xlsx must begin `PK\x03\x04`, a `.csv`/`.json` must decode as
  UTF-8, and a `.json` must parse. Nothing is converted — the bytes are stored as uploaded.
- `GET /frontend/v1/uploads/{upload_id}/bytes` → the bytes, workspace-scoped, `Cache-Control:
  private`; an upload this workspace never made is `404 UPLOAD_NOT_FOUND` (absent, not "forbidden").
  Browser path: `/api/clue/frontend/v1/uploads/{upload_id}/bytes`.

### Submission

- Turn and Home submissions take `attachment_refs[]`, each item
  `{upload_id, artifact_key, sha256, media_type, byte_count, filename}` — all six required. Every
  field is re-read from the upload row inside the submitting workspace and compared; a receipt is a
  claim, never authority.
- Limits (settings, all in `.env.example`): at most `CLUE_CHAT_ATTACHMENT_MAX_FILES` = 10 per
  message, `CLUE_CHAT_ATTACHMENT_MAX_TOTAL_BYTES` = 150 MB total,
  `CLUE_CHAT_ATTACHMENT_IMAGE_MAX_BYTES` = 10 MB per image,
  `CLUE_CHAT_ATTACHMENT_TEXT_MAX_BYTES` = 5 MB per text file,
  `CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES` = 25 MB per document. The size check runs before the
  content check, so an oversized PDF refuses `UPLOAD_TOO_LARGE`, not `UPLOAD_NOT_A_DOCUMENT`.
- Refusals: `404 ATTACHMENT_NOT_FOUND` (a receipt naming an upload this workspace never made),
  `409 ATTACHMENT_MISMATCH`, `422 ATTACHMENT_LIMIT_EXCEEDED` / `ATTACHMENT_DUPLICATE`.
  `503 CAPABILITY_UNAVAILABLE` for a storage-less deployment exists only at the validator level —
  the submission routes are not registered without storage, so it is unreachable over HTTP.
- Acceptance is all-or-nothing: a refused attachment takes the whole turn with it.
- `composer_capabilities.attachments` is true exactly when the deployment has artifact storage.

### Transcript

- Refs with `flavor: "attachment"` carry `label` (the human's filename), `media_type` and
  `upload_id`, on both the pending-submission and the durable read, so a chip looks the same before
  and after finalization. `object_type` is `"artifact"`, `object_id` the artifact key.
- Image chips render from `GET /frontend/v1/uploads/{upload_id}/bytes`; text chips carry no URL.

### What the agent receives

- Every attached file — text, image or document alike — reaches the agent the one way: as a file
  in the read-only `attachments/` folder of the agent's workspace (2026-09-19 ruling). No
  attachment becomes a project document, and none is listed in the Gallery.
- Every attachment is named on the turn's L7 context line with where it is readable and which tool
  opens it: `read_file` for the text family, `run_python` for the document family (the skill adds
  that a small `.csv`/`.json` is plain text and opens with `read_file` too). `run_python@1` is the
  agent writing Python against the file in a no-network Docker sandbox over the thread's workspace.
  A deployment that has not built the sandbox image (`make sandbox-image`) or that sets
  `CLUE_SANDBOX_ENABLED=false` (it defaults to `true`) cannot read binary documents at all — the tool refuses
  `sandbox_unavailable` and the agent says so.
- Images are sent to the model as image parts on the sending turn, and re-sent for prior turns of
  the same thread, newest first, up to `CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX` (default 20;
  `0` = no cap). Erased or tombstoned history images are skipped.
- Uploaded images do **not** appear in the Gallery (founder ruling 2026-09-18).

### Ad design leg

While an ad design leg is open, images attached through `+` or dropped on the chat keep the
existing design-reference route (design API upload, `design_asset` context refs, at most 4); text
and document files take the attachment route above. The two caps apply separately; the design
refusal is shown first.

## Research quality context pins — approved 2026-09-22, implementation in progress

Research pins the exact project ICP and compatible persona documents, whether inherited from the
brand or explicitly overridden by project variants, along with selected product/capability evidence.
All account, person and narrative work in a run consumes this immutable context. Quality pages and
refreshes carry project/context/generation identity as described in the accounts contract's
“Research quality generations” amendment. Changing project targeting creates a new context; it
cannot silently rewrite the meaning of an old run or replace another project's narrative.

## Product change notices (2026-10-15)

Spec `docs/superpowers/specs/2026-10-15-product-management-design.md` §7. A merge or removal of
products in Brand context moves every project whose current product set used them (a new
product-set version tagged with the change), and the project's chat shows one line per change.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/frontend/v1/projects/:projectId/product-notices` | `{notices: [{changeId, text, outcome, createdAt}]}` — the last 30 days, minus those this person dismissed. `outcome` is `updated`, `needs_choice` (the project had no other product and keeps its old set), `restored` or `left_as_is` (an undo). |
| `POST` | `/frontend/v1/projects/:projectId/product-notices/:changeId/dismiss` | `204`; per person. |

Shown only in the project's chat, above the transcript (founder answer 2026-10-15).

## CRM write permission card (2026-10-22)

CRM integration Phase 2; card spec
`docs/superpowers/specs/crm-integration/2026-10-22-crm-write-permission-card-design.md`. When the
Head of ABM proposes CRM changes no standing permission covers, its turn ends on an `agent_gate`
of kind `crm_write_permission`, rendered by `CrmWritePermissionCard`.

- **The card's content** is the gate's `subject_snapshot` (`card_snapshot` in
  `platform/api/clue_api/crm/write_prepare.py`): `crm`, `title`, `description`, `groups[]`
  (`kind`, `object`, `field_label`, `list_ref`, `title`, `count`, `value_summary`, `reason`,
  `records[{write_id, name, before, after}]`, `scope_key`, `always_allow`), `overwrites_heading`,
  `overwrites[]`, `standing_permissions[{scope_key, phrase}]`, `caption`. Parsed by
  `crmWriteCard` (`features/integrations/model/crm-write.ts`). The gate's `subject_ref` is
  `crm_write_proposal:<proposalId>`; it has no `subject_revision` and no amount.
- **Gate list** gains `withdrawn: bool` (default `false`): nobody answered and it can no longer
  be answered (a newer card replaced it, or a reconnect closed it). A withdrawn gate is never open;
  the card reads "Replaced by a newer proposal", or "These changes were not sent" when the
  progress read says `closed`.
- **Answer:** `POST …/turns` with `gate_response.crm_write = {selected_write_ids, always_allow}`
  for Allow; "Don't allow" is `decision: "rejected"` with no `crm_write`. Any member of the
  workspace may answer (R-6.8), so the addressee rule does not apply to this kind. Refusals shown
  on the card, which stays as it was: `422 CRM_WRITE_NOTHING_SELECTED`,
  `422 CRM_WRITE_UNKNOWN_CHANGE`, `409 CRM_CONNECTION_CHANGED`, `409 GATE_REPLACED`,
  `409 CRM_WRITE_ALREADY_ANSWERED` (another member's answer got there first: "Someone answered
  this card first."; the card then reads its gate again).
- **Progress:** `GET /frontend/v1/crm/proposals/:proposalId` → `{proposalId, state (asking |
  sending | paused | done | declined | replaced | closed), provider, counts{done, failed, skipped,
  pending}, groups[{…, chosen, done, failed, skipped, pending}], overwrites[], failed[{writeId,
  label, field, crmMessage}], skipped[{writeId, label, reason}], answeredBy, answeredByName,
  answeredAt}`. Read once an answered or withdrawn card is shown, then every 2 s while `sending`
  and the tab is visible.
