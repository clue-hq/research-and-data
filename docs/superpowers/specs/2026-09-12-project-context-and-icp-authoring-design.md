# Project context files, ICP authoring, the plan document, and research reads — design

**Date:** 2026-09-12. **Status:** founder-approved in conversation (this document records the
rulings). **Lane:** `research-streaming`, worktree `san-salvador`.

**Plans that implement it, in build order:**

1. `docs/superpowers/plans/2026-09-12-project-context-files.md` — the per-project folder
   (`status.md`, `decisions.md`), its per-turn pin, and its index card.
2. `docs/superpowers/plans/2026-09-12-icp-authoring.md` — project-scoped knowledge documents,
   the ICP authoring tool, the persona synthesis request, skill v23 / profile v46.
3. `docs/superpowers/plans/2026-09-12-project-plan-document.md` — the agent-written,
   user-editable `plan.md` (backend, tool, read/write routes, grant).
   `docs/superpowers/plans/2026-09-12-plan-tab-frontend.md` — the Plan tab, the plan card,
   auto-open, gallery document cards (DEFERRED, ruling R12).
4. `docs/superpowers/plans/2026-09-12-head-of-abm-read-tools.md` — three read tools over ARV2
   rows so the agent can answer about accounts, research and discovery from the claim store.

---

## 1. The problem, as observed

Two things the founder saw on 2026-09-12 while walking the project conversation:

1. **A second thread of the same project knows almost nothing of the first.** The intent, the
   chosen ICP, the product set, the strategy discussion, a discovery run launched from another
   thread, research already completed — none of it reaches the next thread.
2. **The agent refuses to author an ICP** ("I cannot author a new ICP document here … it needs a
   new onboarding synthesis on the Knowledge page") when the user's own profile differs from
   every brand-level proposal.

## 2. Why it happens (verified against the tree)

- A production project-conversation turn composes four things: the brand card, the
  brand-knowledge index card (one line per brand file, read by path from
  `inputs/brand/knowledge/`), a small envelope (project id, name, status, brand, product, thread),
  and L6 = **this thread's** history (`load_head_of_abm_history` is keyed on
  `(workspace_id, thread_id)`). Nothing project-level and durable is composed beyond the ICP pin
  and the product set, which ride the index card.
- Skill v22 §6 sends every preference, boundary and decision through the `project_state` route
  of `record_interview_answer`. Those rows land in `volunteered_statement` (append-only,
  latest-correction-wins via `correction_of_id`) and **nothing in production reads them back**:
  ruling D5 (O6) removed the Stage-0 project-state card, and its resolvers were retired. The
  route is write-only today.
- ARV2 discovery and research state is invisible to the agent: the one read it holds
  (`read_arv2_account_research_run@1`) needs a run id it only knows from its own thread's launch
  receipt. There is no tool to list a project's accounts, read an account's research, or read a
  discovery run.
- ICP authoring is forbidden by skill text (v22 §3, §5, §10) and by the absence of a knowledge
  document write tool on profile v45. Every substrate piece already exists: immutable versioned
  document rows with `supersedes_document_id`, the human editor's save path that mints a new
  version and demotes `confirmed` to `proposed`, the confirmation gate over any document by id and
  digest, the append-only project pin, and the synthesis launcher's one-persona-turn-per-ICP
  entry point.

## 3. Rulings (founder, 2026-09-12)

- **R1 — files are the shared medium.** A per-project folder is materialized into the agent's
  workspace next to the brand folder. One bounded index card lists both. The agent reads what it
  needs by path (S4 already rules this).
- **R2 — most project files are deterministic, not agent-written.** `status.md` is compiled from
  ARV2 rows with no model call. `decisions.md` is rendered from the live `project_state`
  statements. Only `plan.md` and authored ICP/persona documents are model-written.
- **R3 — the plan is written once the discussion is done.** The agent writes `plan.md` only after
  the first-principles interview has settled the intent, the ICP and the product set for the
  project — never on the first turn. The plan is intent; `status.md` is fact; they stay separate.
- **R4 — the Head of ABM may author ICP documents.** Through a governed tool that stores a
  `proposed` version; the human still confirms through the existing gate. The agent drafts from
  the brand files only (its surface has no web tool). Scope is the user's choice: brand-level or
  project-local. A project-local variant is a full document carrying `derived_from` (ruling
  2026-09-10), with its own `icp_key`.
- **R5 — personas follow the ICP.** A persona document for an authored ICP is produced by the
  existing synthesis persona turn, requested through a tool, once the ICP is confirmed and pinned.
  Small persona edits may go through the document tool; redrafts go through the synthesis turn.
- **R6 — presentation truth for markdown documents is the dummy's Plan tab** (screenshot
  2026-09-12, `10m+ landing page campaign`): a third rail tab beside Gallery and Target accounts,
  a slim header with a file icon and the document's name, and a centred markdown article. The
  chat shows a collapsible "proposed a plan" card that opens the tab. The same document surface
  renders project-scoped ICP and persona documents when opened from the gallery. Every addition
  uses the platform's `--clue-ds-*` tokens; no raw hex, no raw font stacks.
- **R7 — the user edits documents on the same versioned path the agent writes.** A save is a new
  immutable version with `expectedRevision` conflict detection (the Knowledge editor's contract,
  merged 2026-09-12). The agent's write tool refuses when the current version is not the one it
  read, so a user edit is never silently overwritten.
- **R8 — the read tools serve ARV2 rows only** (standing rule "ARV2 schema is the only truth").
  No bridge to the old lane's tables.
- **R9 — build order:** project files → ICP authoring → plan document → read tools.
- **R10 — external libraries only for markdown (revised 2026-09-13).** Preview is `react-markdown` + `remark-gfm`; the founder selected MDXEditor for visual editing. This supersedes the CodeMirror source-editor choice. MDXEditor owns formatting, parsing, serialization and any source/code editor plugins; no in-house Markdown engine or parallel source editor.
- **R11 — one shared library toolbar (revised 2026-09-13).** Compose MDXEditor's controls for undo/redo; headings; bold, italic, strikethrough, inline code; bullet, numbered and task lists; blockquote, code block, horizontal rule; link and table. The native block selector and table editing replace custom heading buttons and source templates. Image/video insertion remains outside v1. Apply Clue tokens/icons and preserve existing Save/Discard/version behavior. `docs/superpowers/specs/2026-09-12-markdown-editor-toolbar-design.md` holds the revised brief; no custom CodeMirror command/keymap layer is required.
- **R12 — this pass ships the backend and the agent capabilities only.** The Plan tab, the document surface and the gallery document cards are the deferred plan `2026-09-12-plan-tab-frontend.md`, executed later with the toolbar slice.

## 4. Design

### 4.1 The project folder (plan 1)

Materialized read-only under `inputs/project/` on every production project-conversation turn:

| path | source | written by |
|---|---|---|
| `inputs/project/status.md` | `project_icp_pin`, `project_product`, `arv2_discovery_run` + candidates, `arv2_research_run` + jobs, `project_account`, the project's documents | deterministic compiler, per turn |
| `inputs/project/decisions.md` | `volunteered_statement` (`route_kind='project_state'`, current-effective) with quotes resolved from the captured input artifacts | deterministic renderer, per turn |
| `inputs/project/plan.md` | `brand_knowledge_document` row, `project_id` set, kind `project-plan` | the agent (plan 3), the user (plan 3) |
| `inputs/project/audience/icp-<key>.md`, `persona-<key>.md` | `brand_knowledge_document` rows with `project_id` set | the agent / synthesis (plan 2) |

**Byte stability across retries.** Seeds are frozen and re-verified byte-for-byte on a reclaimed
turn (`AgentResourceMaterializer.verify_materialized`), so the compiled files must not move
between attempts of one turn. The compiled bytes are persisted as artifacts and recorded
insert-once in a new table `agent_turn_project_files` (turn id → files), exactly as
`agent_turn_knowledge_pin` freezes the brand set. Every retry reads the winner.

**The index card.** A second bounded L3 artifact, `ProjectFilesIndexCard@1`
(`card_kind = "project_files_index"`, materialized at `context/project/project_files_index.json`),
one entry per project file: `path`, `workspace_path`, `kind`, `version`, `status`, `summary`.
The brand card is untouched (its schema and digest tests stay green).

**Skill v23 §1** adds: read `inputs/project/status.md` and `inputs/project/decisions.md` before
the first reply on a thread; re-read `status.md` before answering any question about where the
project stands.

`status.md` sections, in order: *Confirmed ICP* (key, version, path, or "not confirmed"),
*Products* (selection version, product ids, or "not confirmed"), *Plan* (version and last update,
or "not written"), *Accounts* (count in the project), *Discovery* (latest run: status, asked,
found, verified, shown, started, finished; "no run yet"), *Research* (one line per run: status,
effort, jobs finished/total; then one line per account job: name, status, stage, person jobs
count), *Project documents* (path, version, status). Timestamps are the rows' own; the compiler
never writes "now".

`decisions.md`: one bullet per current-effective statement, `route_key` in bold followed by the
verbatim quote, oldest first; a statement whose evidence was erased is omitted; a corrected
statement shows only its latest form.

### 4.2 Project-scoped documents and ICP authoring (plan 2)

**Schema.** `brand_knowledge_document` gains `project_id text NULL` (FK `(project_id,
workspace_id) → project`) and `derived_from_document_id uuid NULL` (self-FK). The uniqueness
`(workspace_id, brand_id, path, version)` becomes a unique index over
`(workspace_id, brand_id, COALESCE(project_id, ''), path, version)`. The folder CHECK admits
`project`; the kind CHECK admits `project-plan`. Every brand-level reader adds
`project_id IS NULL`; project readers add `(project_id IS NULL OR project_id = :project_id)`
where a brand document is a valid answer (the ICP gate's key lookup) and `project_id =
:project_id` where only project documents are wanted (materialization, the Plan surface).

**Tool `author_icp_document@1`** (composition root, WRITE, `DOMAIN_IDEMPOTENT`, pin `project`).
Model-visible input: `icp_key` (kebab, ≤ 60 chars), `document` (the full markdown including the
front matter the icp-synthesis skill mandates), `scope: "brand" | "project"`,
`derived_from_icp_key: str | null`. Trusted input: `source_turn_ref`. The platform:

1. parses the front matter; refuses `icp_front_matter_invalid` unless `kind: icp-definition`,
   `icp_key` equals the input, `product_ids` is a non-empty list of strings, and `hard_gates` is
   a non-empty list;
2. overwrites `status: proposed`, `brand_id`, `project_id` (project scope only), `derived_from`
   (the brand document id when named), `authored_by: {turn_id, user_id}`; drops any
   `confirmed_*` / `product_selection_version` keys;
3. refuses `icp_key_taken_by_brand` when scope is `project` and a brand-level document with that
   key exists (a variant gets its own key); refuses `icp_key_taken_by_project` in the mirror case;
4. renders with `render_markdown`, records the artifact, inserts the row at
   `audience/icp-<key>.md`, version `MAX+1` for that scope, `supersedes` the newest servable
   same-scope row, retires `ready`/`proposed` same-scope rows (never `confirmed`);
5. document id = `uuid5("arv2-icp-authoring:{turn_id}:{scope}:{icp_key}")` so a replay returns
   the same row; the `brand_knowledge_document_path_version` `IntegrityError` becomes the typed
   refusal `icp_document_version_race`.

The existing gate `open_icp_confirmation_gate@2` then confirms it: `current_icp_document` gains a
`project_id` argument and prefers the project-local row for this project;
`confirm_icp_document` carries `project_id` and `derived_from_document_id` onto the confirmed
version. The pin is unchanged.

**Tool `request_persona_synthesis@1`** (composition root, SPEND, `DOMAIN_IDEMPOTENT`, pin
`project`). Input: `icp_key`. Preconditions: the key names this project's pinned ICP; no
`personas` run for that document is `queued`/`running`. Effect: inserts an `onboarding_run` with
`kind = 'personas'`, `project_id`, `persona_icp_document_id`, and enqueues the existing
`ONBOARDING_RUN` fleet task with `kind: personas` in the payload. `OnboardingRunWorkHandler._run`
branches on the kind and runs exactly one `_persona_step` for that ICP, then `finish_run`. The
persona document is written in the ICP's scope (`RegisteredIcp` gains `project_id`). The full
onboarding route's `onboarding_in_progress` check and `read_current_run` consider `kind = 'full'`
only.

**Skill v23** rewrites §3, §5 and §10: when the user's profile differs, or none fits, or the gate
returns *revised*, draft the profile from the brand files, ask whether it is brand-level or
project-only, author it, then open the confirmation gate on it; after confirmation, offer the
persona synthesis. **Profile v46** grants both tools; **recipe v24** admits them.

### 4.3 The plan document (plan 3)

**Tool `write_project_document@1`** (composition root, WRITE, `DOMAIN_IDEMPOTENT`, pin
`project`). Model-visible input: `document: "plan"`, `body` (markdown, no front matter),
`expected_version: int | null` (null only when no version exists). The platform writes the front
matter (`kind: project-plan`, `project_id`, `status: ready`, `authored_by`, `supersedes`),
stores `project/plan.md`, and refuses `project_document_revision_conflict` when the current
version differs from `expected_version` — the agent must re-read the file (the user may have
edited it). The finalization's `domain_refs` carry
`{object_type: "project_document", object_id: <document_id>, version: <version>}`; the turn
stream projects it as a `plan` part titled "Plan" with `revision_label = "v<version>"`.

**Read/write surface.** `GET /frontend/v1/projects/{project_id}/documents` (the project's
current servable documents), `GET …/documents/{document_id}` (markdown, version, updatedAt,
front matter), `PUT …/documents/{document_id}` with `{body, expectedRevision}` on the exact
contract of the Knowledge editor's PUT (new immutable version, `user_edit` stamp, 409
`DOCUMENT_REVISION_CONFLICT`). `project.write` required.

**Frontend.** Surface `"plan"` joins `ChatShellSurface`, `EditorShellSurface` and the URL
vocabulary (`?surface=plan`). A third tab in `ArtifactTabs` (file icon + "Plan"). A `hidden`-
toggled pane in `ArtifactStage` mounting `ProjectDocumentSurface` (breadcrumb header, Preview /
Edit segmented control, Save / Discard, markdown article), using shared `MarkdownArticle`
(react-markdown + remark-gfm) and `MarkdownEditor` (MDXEditor) components. The Knowledge
editor's draft state machine is generalized with an injected save; initial normalization is not
an edit and dirty drafts survive refreshed versions. A pure `planWriteToOpen` signal opens the
tab once for a newly received plan part with `planRef.objectType === "project_document"`;
parts present at initial hydration are banked without opening it. This follows the 2026-09-13
lane-index revalidation and is independent of the authoring tool. Clicking the plan card calls
`openPlan`. The same surface opens a project ICP/persona document as a rail tab when chosen from the gallery, where
project documents appear as document cards (file icon, title, edited label; no thumbnail).

### 4.4 Read tools (plan 4)

Three READ tools in `platform/api/clue_api/arv2/`, `EFFECT_FREE`, pin `project`, granted on
profile v48 with skill v25 and recipe v26:

- `read_project_accounts@1` — `project_id` → up to 200 accounts in the project: entity id,
  canonical name, domain, ARV2 research status and refreshing flag, added_via, added_at.
- `read_account_research@1` — `account_entity_id`, `section: "overview" | "claims"` → for
  `overview`, the live `display_block` sections of the account's overview page (bodies and cited
  claim ids) or the typed refusal `overview_not_written`; for `claims`, the account's live claims
  grouped by field key (value, source url, evidence span ≤ 240 chars, tier), capped at 120.
- `read_discovery_run@1` — `project_id`, optional `run_id` → the latest (or named) run's status,
  counts, timestamps, and up to 50 candidates (name, domain, pass, disposition, decision, fit).

Skill v25 §7b and a new §7c teach when to read (before answering about an account, before
proposing more discovery, before claiming research is done).

## 5. Out of scope

- Switching a project's pinned ICP to another version (future work per 2026-09-10 rulings).
- A gallery thumbnail image for documents (documents render as cards with an icon).
- Editing brand-level documents from the project surface (the Knowledge page owns that).
- Cross-thread summaries by a model (L6 stays thread-scoped; the files carry the shared state).
