# Composer `@` tagging of files, microsites and accounts — design

**Status:** approved by the founder 2026-09-17 (three follow-up rulings taken the same day: spaces
allowed in the search query with self-closing on no match, Home composer keeps the flat accounts
list, no profile-text change in the first cut). Rulings taken in discussion the same day:
categories **Files / Microsites / Accounts**; scene ads and tables live under **Files**; the
Gallery is the file system and **no path or id is ever shown** to the user; a tagged design
artifact is a **reference only** and never opens or routes a design leg (Head-of-ABM decides that
by reasoning); the picker offers **only the latest version** of each item, and a tag **pins the
version** it was sent with; **typing searches across all categories**, an empty query browses by
category; tagging **does not open** the item's Gallery tab; the existing cap of **100 refs per
turn** stays; an empty category shows one line.

## 1. The problem

The composer's `@` picker today lists workspace accounts and their committee contacts, and
nothing else. A user who wants to talk about the plan, a persona doc, the target-account table,
a LinkedIn ad or a landing page has no way to point at it. They paste titles, or describe the
thing, and the agent guesses which object they mean.

The picker also rendered invisibly until 2026-09-17 (commit `89f34dd4e`): the editor shell hid
overflow and clipped the listbox. That is fixed and out of scope here; it is why the founder had
never seen the existing picker.

## 2. What exists (verified 2026-09-17)

**Wire.** `POST /projects/{p}/threads/{t}/turns` takes `context_refs: [{object_type, object_id,
version}]`, `object_type ∈ {account, contact, design_document, design_node, design_asset}`
(`chat/schemas.py:196-205`), at most 100 per turn. The same tuple rides `POST /projects` (Home
bootstrap) and `POST …/composer-context/prepare`.

**Validation.** `chat/composer_context.py::validated_context_refs(conn, *, workspace_id, refs,
design_leg_document_id=None, storage=None)` checks tenancy, duplicates, and per type: accounts
and contacts must exist, be unmerged, not be the client's own entity, match `canonical_version`
when a version is given; `design_document` must exist and match `current_version` when a version
is given; `design_node` and `design_asset` require an open scene leg. Error codes map to 404 / 409
/ 422 / 503 in `router.py:609-646`.

**Persistence.** `agent_turn_submission_context_ref (turn_id, workspace_id, ordinal, object_type,
object_id, object_version)`, with a CHECK on `object_type` last widened by migration
`db145059253b` (design_asset). The fleet re-reads the refs by `turn_id`
(`agent_turn_fleet_wiring.py:418-422`).

**Routing.** One indexed read decides who receives the turn: an open design leg on the thread, or
Head-of-ABM (`agent_turn_fleet_wiring.py:433-441`). Context refs of any type play no part. A leg
is opened only by the `open_design_leg@4` tool. This already matches the founder's ruling; the
spec keeps it that way by construction.

**What the agent sees.** Each submitted ref becomes one L7 system line ("Current human-message
context reference … object_type=… object_id=… version=…", `clue_agents/context.py:601-628`) and,
when a compiled card exists, one L5 focus card at `context/focus/<type>-<hash>.md`. The card
reader (`account_research_turn_wiring.py::DbCompiledContextCardReader.read`) already compiles
`account`, `contact`, `design_document` (a typed summary: id, title, doc_kind, status,
current_version, brand kit pin) and `brand_knowledge_document` (the full markdown body). A ref
with no card is silently skipped at L5. Any account ref also triggers the account deep-steering
artifacts in L3 (`agent_turn_fleet_wiring.py:1062-1076`).

**Agent-side file system.** Every project document is mounted read-only under the `project`
mount at its workspace path (`project/plan.md`, `project/audience/icp-gi.md`;
`project_context_files.py:116-139`). Design artifacts are listed in
`project/artifacts/index.json` and read through `read_artifact@1 {artifact_id, section}`.

**Project documents.** Table `brand_knowledge_document` with a non-null `project_id`. Each
version of a path is its own row with its own `document_id` (derived from turn, path, version,
sha; `arv2/project_documents.py:239`). The Gallery read `GET
/frontend/v1/projects/{p}/documents` serves the latest servable row per path as `{id, path, kind,
title, version, status, updated_at, icp_key}`.

**Design artifacts.** `GET /projects/{p}/design-artifacts` serves the project's design documents
as `{id, document_id, kind: web|ad, title, status, current_version_id, artifact_type, …}`; `id`
and `document_id` are both the design-document id; `current_version_id` is the CAS counter as a
string.

**Frontend.** Slate editor with a mention plugin (`project-composer-editor.tsx`): trigger regex
`/(?:^|\s)@([^\s@]*)$/`, `EntityPicker` listbox grouped Account / Contacts, mention element
`{type:"mention", entityId, entityType: account|contact, label, secondaryLabel, imagePath,
accountName?}` (no version). On send, `chat-surface.tsx:661-670` maps mention ids back to the
catalog `controller.composerEntities` (= backend `context_entities`) and posts `{objectType,
objectId, version}`. The transcript renders context refs as chips by matching `workspace.entities`
by id+type, then `ref.label`, then a per-type fallback (`chat-transcript.tsx:100-140`). The
backend merges `label`/`media_type`/`thumbnail_digest` into echoed `design_asset` refs only. The
page already loads both the project documents (`useProjectDocuments`) and the design-artifact
feed (`loadGalleryFeed` → `artifacts`, `documentIds`) for the Gallery.

## 3. Design

### 3.1 One new ref type, one reused

| Category | `object_type` | `object_id` | `version` |
|---|---|---|---|
| Files: project documents | **`project_document`** (new) | the latest row's `document_id` | that row's `version` |
| Files: scene ads | `design_document` (existing) | design-document id | `current_version` |
| Microsites | `design_document` (existing) | design-document id | `current_version` |
| Accounts / contacts | `account` / `contact` (existing) | entity id | `canonical_version` |

`design_document` is reused because a mention and a leg's target document are the same object;
the difference is what accompanies it (nodes) and who receives the turn (routing), and neither
is decided by the ref. A design-document ref with no nodes, on a thread with no open leg, is
exactly a mention today and is already accepted; the spec makes that contract explicit.

`project_document` is new on the wire, in the CHECK, in validation and in the card reader.
The name says what the user tagged; the storage table stays incidental.

### 3.2 Validation (`composer_context.py`)

`validated_context_refs` gains a keyword `project_id: str | None = None`. The submit route and
the prepare route pass the project; the Home bootstrap has no project yet and passes `None`.

- **`project_document`**: `object_id` must parse as a UUID, else `CONTEXT_REF_NOT_FOUND`. The
  row must exist in `brand_knowledge_document` with this `workspace_id` and this `project_id`
  (with `project_id=None` every `project_document` ref is `CONTEXT_REF_RELATIONSHIP_MISMATCH`),
  have a servable status and a non-null `artifact_key`, else `CONTEXT_REF_NOT_FOUND`. `version`
  is required for this type (a tag always pins); `None` is `CONTEXT_REF_STALE`. The row must be
  the latest servable row for its path (the same `DISTINCT ON (path) … ORDER BY version DESC`
  rule the Gallery read uses), else `CONTEXT_REF_STALE`. A stale tag is refused, not silently
  repointed: the user re-tags from the picker, which only ever offers the latest.
- **`design_document`** additionally, when `project_id` is given: the document must be one of
  `project_design_documents(project)` (unarchived), else `CONTEXT_REF_NOT_FOUND`. A version is
  required for a mention as well; the existing `current_version` match stays.
- Everything else is unchanged, including the four-asset cap and the account/contact rules.

### 3.3 Persistence

One migration widens the `agent_turn_submission_context_ref` CHECK to add
`'project_document'`, chained off the current head, with a matching `downgrade()`. The existing
enum-parity/CHECK tests are extended to cover the new value.

### 3.4 What the agent sees

- **L5 focus card, new branch `project_document`** in `DbCompiledContextCardReader.read`: a
  minimal typed summary, not the body. `{"document_id", "path" (the agent's workspace path,
  e.g. `project/audience/icp-gi.md`), "title", "kind", "version", "status", "updated_at"}`,
  `version` = the row's version. The body already sits under the `project` mount; the card tells
  the agent where. This mirrors the `design_document` card, and deliberately does not reuse the
  `brand_knowledge_document` branch, which inlines whole documents.
- **L7 line**: unchanged. It already carries type, id and version in submission order.
- **Design artifacts**: the existing `design_document` card. Its summary has the id the agent
  passes to `read_artifact@1`.
- **Routing, account steering, gates**: untouched. Head-of-ABM reads the cards and the message
  and decides for itself whether to call `open_design_leg@4`.
- **Profile text**: no change in the first cut. If the live walk shows Head-of-ABM ignoring a
  tagged file, one sentence goes into the profile under the usual founder review of skill text.

### 3.5 Transcript echo

`MessageObjectRef` presentation keys are merged for two more types, the way `design_asset` gets
them today (`schemas.py:991-996`, producer `composer_context.py:480-519`):

- `project_document` → `label` = the document's title, `kind` = its document kind.
- `design_document` → `label` = the design document's title, `kind` = `web` or `ad`.

The label is read at echo time from the referenced row, so a renamed document shows its name at
the time the transcript is read, and a deleted one falls back to the frontend's fallback label.
No path, no id, reaches the transcript text.

### 3.6 Frontend catalog: the Gallery is the file system

No new backend read. The picker's Files and Microsites entries are built client-side from the
two feeds the Gallery already renders:

- **Files** = every project document from `useProjectDocuments` (`kind` label via
  `documentKindLabel`) + every design artifact with `kind === "ad"` (label = title, secondary =
  the collateral type label, e.g. "LinkedIn ad"; falls back to "Ad").
- **Microsites** = every design artifact with `kind === "web"` (secondary "Microsite").
- **Accounts** = the existing `workspace.entities` (accounts, each followed by its contacts).

The `ProjectEntity` model widens `type` to `account | contact | project_document |
design_document`, and gains `category: "files" | "microsites" | "accounts"` and an optional
`icon` (document / ad / microsite). `version` becomes required for the two new types
(`document.version`, `Number(currentVersionId)`). `imagePath` stays for accounts and contacts
only. The catalog is memoised per project from `(documents, artifacts, workspace.entities)` in
the workspace controller and exposed as `controller.composerEntities`, so the send path
(`chat-surface.tsx:661-670`) needs no change beyond the type widening.

Both feeds already list only the latest version per item, which is the ruling.

### 3.7 Picker UX (two-level, Cursor-shaped)

- `@` with an **empty query** shows three rows: Files, Microsites, Accounts, each with a count
  and a chevron. Enter / ArrowRight / click opens that category as a flat list with a first row
  "← Back" (ArrowLeft / Backspace on an empty query also goes back). The same keyboard model as
  today inside a list: ArrowUp/Down, Enter or Tab to insert, Escape to close.
- **Typing** after `@` searches all three categories at once, grouped under small headers
  (Files / Microsites / Accounts), matching on label, secondary label and account name. The
  category rows disappear while a query is present.
- A category with nothing in it shows one line: "No files in the Gallery yet", "No microsites
  yet", "No accounts yet". A query with no match anywhere shows "No matches".
- The `@` button's `aria-label` becomes "Add context"; the listbox's "Choose context".
- A mention chip in the draft shows an icon by type and the label; the `title` attribute shows
  label and secondary label. No path.
- The mention element gains `version` and the widened `entityType`, so a chip carries what the
  send path needs even after the catalog refreshes underneath it.

**Query spaces (ruled 2026-09-17: yes).** Today the query ends at the first space, so "@Project plan"
searches "Project" only. Proposed: allow spaces while the picker is open (`/(?:^|\s)@([^@\n]*)$/`,
query capped at 60 chars) and close the picker automatically when the query has no match in any
category and ends with a space, so ordinary prose such as "meet @ 5pm and …" recovers by itself.
Escape still closes at once. This is the one behaviour change that touches typing outside the
picker, so it is called out rather than assumed.

### 3.8 Home composer

The Home composer bootstraps a project that does not exist yet, so it has no Files or Microsites.
It shows only the Accounts category (no category rows: today's flat list). `project_document`
refs on `POST /projects` are refused by validation (`project_id=None`).

### 3.9 Transcript chips

`chat-transcript.tsx` renders the two new types from the echoed `label` with per-type fallbacks
"Selected file" and "Selected design", and a small icon by type. Chips never link anywhere in this
cut (ruling: tagging has no side effects; opening is a Gallery gesture).

## 4. Out of scope

- Opening the Gallery tab from a chip or on tag.
- Tagging a specific older version, folders, or anything path-shaped in the UI.
- Multi-file drag or attachment upload (the `attachments` capability stays `false`).
- Any change to routing, the design leg contract, or the Head-of-ABM profile text.
- Contacts as their own category (they stay nested under Accounts as today).

## 5. Acceptance

1. In a project with documents, ads, a microsite and accounts, `@` shows three category rows;
   each opens the right flat list; titles only, no paths or ids anywhere in the DOM text.
2. Typing `@plan` lists the plan under Files and any account containing "plan" under Accounts.
3. Tagging the plan and sending "summarise this" produces a persisted turn whose context ref is
   `project_document` with the plan's current version, and the agent's L5 has a focus card naming
   `project/plan.md`; the transcript chip shows the plan's title.
4. Tagging a microsite and sending "what does this page say about pricing?" leaves routing on
   Head-of-ABM (no leg opened); the agent answers from `read_artifact@1`. Sending "change the
   headline of this page to X" lets Head-of-ABM open a design leg by its own reasoning.
5. A tag whose document has since gained a newer version is refused with 409 `CONTEXT_REF_STALE`
   and the composer surfaces the existing stale-ref message.
6. Home composer shows only accounts.
7. Gates: backend `tests/api` for validation (each refusal code), the CHECK migration up/down,
   the reader branch, and the echo labels; frontend node tests for the catalog builder, the
   search/grouping model, the mention element serialisation with version, and the chip fallback;
   `npm run lint && npm run build` green; contract notes in
   `apps/frontend/docs/api-contracts/projects.md`.
