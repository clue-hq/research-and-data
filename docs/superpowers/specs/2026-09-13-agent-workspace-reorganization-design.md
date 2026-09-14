# The agent's workspace, reorganised — design

**Date:** 2026-09-13. **Status:** founder-agreed in conversation (this document records the
rulings; no plan is drawn yet). **Lane:** `research-streaming`, worktree `san-salvador`.

**Supersedes, in part,** `2026-09-12-project-context-and-icp-authoring-design.md`: its R1 (a
per-turn copy of the project folder), the tool shape of R4 and R5 (a tool per document, personas
through an onboarding run), and plan 4's fixed output bounds. Its other rulings stand and are
restated below where they bind this design.

---

## 1. What the live walk and the discussion surfaced

- Every turn rebuilds the whole project context from scratch into a fresh directory: brand
  knowledge (about 330 KB), the compiled project files, the cards, and a private `.deepagent`. The
  platform's real hierarchy (workspace → project → thread → turn) is invisible on disk, and the
  agent has no stable place it returns to.
- Nothing survives a turn except rows. A thread's scratch dies with it; project-level outcomes
  reach the next thread only if some code compiles them into a file again.
- The Head of ABM cannot read a researched account. The claims read builds a result larger than
  the 16 KiB governed-receipt bound and the runtime discards it. The discovery read fails its own
  output contract. Three honest refusals in a parallel fan-out spent the per-turn failure budget
  and killed the turn.
- Writing a document costs a bespoke tool each: `author_icp_document@1`,
  `write_project_document@1`, and personas through `request_persona_synthesis@1`, which enqueues
  a personas-only onboarding run. The agent's authoring freedom is gated by tooling, not by skill.

## 2. What does not move (the constraints this design is built inside)

- **Postgres is the only source of truth.** A file on disk is a rendering of rows, never the record.
- **Documents are versioned and immutable per version.** A save is a new version; a human edit and
  an agent write on the same document meet at an `expected_version` check (R7).
- **Pins are human.** The project's ICP and product set are confirmed by a person, by id, and never
  move by themselves (ruling 2026-09-10). Writing a proposal is free; pinning is a gate.
- **Claims are born from resolvers and judges with evidence spans.** The conversational agent reads
  claims freely and writes none. Its own outputs are documents, not claims.
- **Every turn is replayable and every quote is erasable.** A turn records exactly which document
  versions and compiled files it saw; compiled files reverse-bind their quotes to statements.
- **Tool receipts are bounded.** A receipt is journaled, replayed, and re-enters context on every
  later round; 16 KiB stays. What changes is that tools page and spill instead of overflowing.
- **No fake agency (Doc A).** Skills teach; tools act; the runtime enforces. A skill never grants
  authority a tool does not have.

## 3. Rulings (founder, 2026-09-13)

- **W1 — three levels, one hierarchy; a turn is an event, not a place.** The agent's filesystem
  mirrors the platform's: a *workspace library* (brand knowledge), a *project library* (everything
  settled for the project), and *one directory per chat thread* that the agent lives in. There is
  no per-turn directory: a turn rewrites `inputs/` from durable artifacts when it starts and
  snapshots `outputs/` to artifact storage when it finalizes (amended 2026-09-13; the earlier
  four-level shape with a turn directory was judged over-engineered).
- **W2 — the project library is a materialized view of rows.** It is real and persistent on disk,
  refreshed whenever a contributing row changes, and mounted into every turn as a versioned root:
  reads serve the materialized files; a write lands a new document version and re-materializes the
  file (W6). From the agent's side it reads and writes `project/plan.md`; underneath it is a
  version row.
- **W3 — the pinned version is the only one in view.** The library shows the current (pinned or
  latest-ready) version of each document at its plain path. Older versions are reachable by
  explicit request, never listed in the index card, never sitting beside the current file.
- **W4 — artifacts by reference.** The library carries an artifact index (id, kind, title, status,
  version, link), never a copy. A read tool fetches one artifact's content on demand when the agent
  needs it.
- **W5 — the thread's folder persists.** `scratch/` and `reads/` survive across the turns of one
  thread, are unversioned, not part of the record, under one quota with the rest of the thread's
  folder, and purged when the thread is archived or its retention lapses. `scratch/` is the
  agent's notebook, nothing more.
- **W6 — the project is written with the agent's ordinary file tools.** No new governed tool.
  deepagents' own `write_file` and `edit_file` work under `project/`; the backend treats that
  prefix as a *versioned root*: a write there goes through the same document writer the human PUT
  uses, lands a new version row and blob, re-materializes the file, and returns the tool's normal
  result. The path's folder decides the document kind and its validation: `audience/` is an ICP
  (key rules, front matter, lineage), `audience/persona-<key>.md` is a persona document
  (ruling P3-a, 2026-09-14: the platform's existing path, not a `personas/` folder), `plan.md`
  is the plan.
  The expected version is the `version:` in the file the turn was mounted against, never a model
  argument; a stale write, a taken ICP key or a compiled file come back as the write tool's error
  string. One skill per document kind says what a good one contains and where to save it.
  `author_icp_document@1`, `write_project_document@1` and `request_persona_synthesis@1` retire.
  (Chosen over a governed `save_project_document@1` on 2026-09-13: one write verb, `edit_file`
  on project documents, no version argument to mis-copy; the trade is a sync-to-async bridge in
  the backend and the plan card reading rows instead of receipts.)
- **W7 — the pin gate stays.** Saving an ICP stores a `proposed` version. The agent then proposes
  it through the existing confirmation gate; the human's approval pins it. Same for the product
  set. Personas, the plan and decisions are save-and-done.
- **W8 — personas are the Head of ABM's to write.** With a persona skill, in the conversation,
  from the pinned ICP and the brand files already in its context. Onboarding synthesis keeps the
  brand onboarding it was built for and stops being a service the project agent calls.
- **W9 — reads page and spill; they never overflow.** Every read tool takes `offset`/`limit` and
  returns `next_offset`. A result that would exceed the receipt bound is written to
  `reads/<operation_id>.json` and the receipt carries the path, the count and a short summary;
  the agent reads the file in chunks with its file tool. A general claims query tool (entity,
  field prefix, tier, verification status, since; paginated; display-gated) joins the account,
  discovery and accounts reads.
- **W10 — honest read refusals do not spend the failure budget.** A `PreconditionFailed` from an
  effect-free read (`overview_not_written`, `no_claims_under_prefix`, `account_not_researched`,
  `no_discovery_run`) is information the model asked for. Contract violations, receipt overflows
  and plan rejections still count.
- **W11 — brand knowledge is mounted, not copied.** Materialized once per
  `(workspace, brand, knowledge version)` under the workspace library and mounted read-only into
  each turn.

## 4. Design

### 4.1 Layout

```
<CLUE_AGENT_WORKSPACE_ROOT>/<workspace_id>/
  library/                              # W11: workspace library, read-only in turns
    brand/<brand_id>/<knowledge_version>/
      knowledge/{company,product,audience,proof}/*.md
      index.json                        # BrandKnowledgeIndexCard@1, unchanged
  projects/<project_id>/
    library/                            # W2: project library, versioned root
      status.md                         # compiled (plan 1 of the 2026-09-12 set, unchanged)
      decisions.md                      # compiled
      audience/icp-<key>.md             # the pinned ICP only (W3)
      audience/persona-<key>.md         # current version only (ruling P3-a, 2026-09-14: the
                                        #   platform's existing path)
      plan.md                           # current version only
      artifacts/index.json              # W4: references, never content
      index.json                        # ProjectLibraryIndexCard@1
    threads/<thread_id>/                # the backend root: one folder per chat (W1, W5)
      .deepagent/                       # manifest, profile, prompt, skills — rewritten per turn
      inputs/                           # this turn's user message + cards — rewritten per turn
      scratch/                          # the notebook, persists
      reads/                            # W9: spilled tool results, persist
      outputs/                          # snapshotted to artifacts at finalize, then emptied
```

The model's virtual paths are `brand/…`, `project/…`, `manual/…` (plan 2b) and the thread's own
folders at the root. The host layout above is never model-visible. There is no per-turn
directory: the durable record of a turn is its DB pins (knowledge pin, project files pin,
resource manifest digest) and its artifacts (user message, cards, outputs), which is what a
crashed turn is rebuilt from.

### 4.2 Mounting

Today's backend is anchored at one open directory descriptor with `O_NOFOLLOW` walks. It becomes a
**multi-root backend**: a virtual prefix maps to an anchored root, each with its own mode.

| Virtual prefix | Host root | Mode |
| --- | --- | --- |
| `brand/` | `library/brand/<brand>/<version>/` | read-only |
| `project/` | `projects/<project>/library/` | versioned root: read-through, write-through to the document writer (W6) |
| `manual/` | the catalog's manual version (plan 2b) | read-only |
| `scratch/`, `reads/`, `outputs/`, `inputs/`, `.deepagent/` | `projects/<project>/threads/<thread>/…` | the thread root: `scratch/` and `outputs/` writable; `inputs/` and `.deepagent/` platform-written, read-only to the model; `reads/` platform-written |

Symlinks stay refused; the mapping is in the backend, not on disk. One quota per thread covers
the thread's folder and any writable mount; the libraries are not the model's to fill. One live
lease per thread at a time, matching the one-turn-per-thread queue.

### 4.3 Refresh, pinning and replay

- **Refresh triggers.** A new `brand_knowledge_document` version (brand or project scope), a
  `project_state` change, a pin change, an ARV2 run or job reaching a terminal state, a persona or
  plan save, a gallery artifact reaching `ready`. Each re-materializes only the affected files and
  rewrites the library `index.json` (paths, versions, shas, summaries). Compilation of `status.md`
  and `decisions.md` is the plan-1 code, unmoved.
- **What a turn pins.** `agent_turn_project_files` keeps its insert-once role, now recording the
  library index (every file's path, version and sha) the turn was mounted against. Replay
  re-mounts that exact set from artifact storage, not from the live library. Brand knowledge is
  pinned by `(brand, knowledge version)` as today. A crashed turn rebuilds `inputs/` and
  `.deepagent/` from the same artifacts and verifies the same digests; no frozen copy is kept.
- **Concurrency.** Two threads saving the same document meet at `expected_version` (plan 3's
  writer, lock order unchanged). The library is rewritten under the project row lock so a reader
  never sees half a refresh; a turn that started before a refresh keeps its pinned set until it
  ends.
- **DSAR.** Unchanged: compiled files reverse-bind quotes; erasure re-runs the refresh.

### 4.4 Writing to the project (the versioned root)

The multi-root backend's `project/` root is read-through and write-through. `read_file` serves the
materialized file. `write_file(path, content)` and `edit_file(path, old, new)` under `project/`:

1. Resolve the kind from the folder (table below); refuse anything else with
   `unknown_project_path`.
2. Take the expected version from the mounted file's `version:` front matter (`null` when the
   file did not exist at mount time).
3. Run the plan-3 document writer (`project_documents`) on a worker thread with its own
   connection: `_lock_project` first, the revision check, the kind's validation, the INSERT,
   the blob, then re-materialize the library file and its index entry. The version row is stamped
   with the writing turn's id.
4. Return deepagents' `WriteResult`/`EditResult`. A refusal is the result's error string, worded
   for the model as `conflict: <code>: <message>` so a stale read can be told from a bad path
   without parsing prose (landed wording, 2026-09-14):
   `conflict: revision_conflict: plan.md is at version 3, you read version 2 — read it again`;
   `conflict: icp_key_taken_by_brand: …`;
   `conflict: compiled_file_read_only: status.md is compiled from the project's rows; it cannot be
   written`; `conflict: unknown_project_path: write an ICP at audience/icp-<key>.md, personas at
   audience/persona-<key>.md, or the plan at plan.md`; `conflict: icp_not_pinned: this project has
   no pinned ICP; personas follow the project's pinned ICP`.

| Folder | Kind | Validation kept from | Result |
| --- | --- | --- | --- |
| `audience/icp-<key>.md` | `icp-definition` | plan 2: key rules, front matter, `derived_from`, `icp_key_taken_*` | `proposed` version; the agent then opens the gate (W7) |
| `audience/persona-<key>.md` (ruling P3-a, 2026-09-14: the platform's existing path) | `persona` | plan 2 persona document rules, for the project's **pinned** ICP key only (`icp_not_pinned`, `persona_front_matter_invalid`) | `ready` |
| `plan.md` | `project-plan` | plan 3: replay key, revision conflict, `version:` in front matter | `ready` |
| `decisions.md`, `status.md`, `artifacts/`, `index.json` | compiled | — | refused |

These writes are not governed operations: no plan validation, no receipt, no failure-budget
count. The durable record is the version row (turn-stamped). The plan card at turn close and the
inspector read the rows written by the turn instead of a receipt. The human PUT (plan 3's routes)
is the same writer, so a human edit and an agent write meet at the same revision check.

### 4.5 Reads

- `read_project_accounts@1`, `read_account_research@1`, `read_discovery_run@1` gain
  `offset`/`limit`/`next_offset`, keep their gates and refusal codes, and spill when needed (W9).
- `read_claims@1` (new): `entity_id`, `field_prefix`, `tier`, `verification_status`, `since`,
  `offset`, `limit`; the same display gate and `excluded` counts as the account read.
- `read_artifact@1` (new): one gallery artifact's content by id, bounded and spillable (W4).
- Spill contract: `reads/<operation_id>.json` holds the full page; the receipt carries
  `spilled_to`, `count`, `summary`. The file is turn-local and dies with the turn.

### 4.6 Skills

The Stage-0 skill's §1 (files), §5b (author a profile), §5c (personas) and §6b (the plan) become
short document skills the profile grants alongside it: `icp-authoring`, `persona-authoring`,
`plan-authoring`, each stating what the document must contain, the path to save to, and the gate
(if any). §7 (reads) is rewritten for paging and spilling: read in pages, note what you have in
`scratch/`, never state a count you did not read. Skill text is presented to the founder
before it is written (standing rule).

### 4.7 What retires and what stays

- Retire: `author_icp_document@1`, `write_project_document@1`, `request_persona_synthesis@1`
  (kept registered for replay of historical receipts, ungranted from the next profile version), the
  personas-only `onboarding_run.kind`'s production entry point, the per-turn brand copy, the
  `project_files_index` card, and the receipt-based plan-card mapping for `project_document`.
- Stay: the versioned document store and its scope columns, the ICP confirmation gate, the
  compiled `status.md`/`decisions.md`, the display-gated claims read, the human document routes,
  the receipt bound, the workspace security model (fd anchoring, `O_NOFOLLOW`, 0700, segment
  validation, quotas, retention).

## 5. Open questions (to settle when the plans are drawn)

- Retention of a thread's folder: on archive, and after `CLUE_AGENT_WORKSPACE_RETENTION_S` past its newest terminal turn (plan 1 does both; confirm the window).
- Whether the library index card lists artifact references inline or points at
  `project/artifacts/index.json` only (size argument for the latter).
- Whether `read_artifact@1` serves rendered HTML, the design document's JSON, or both.

## 6. Plans to draw, in build order

1. **Thread-rooted workspace with mounts** — the mount table, one persistent folder per thread
   (`scratch/`, `reads/`), per-turn rewrite of `inputs/` and snapshot-then-empty of `outputs/`,
   one quota, thread retention, tests against the security model.
2. **Libraries** — brand library materialization by version; project library materialization,
   refresh triggers, `ProjectLibraryIndexCard@1`, the turn pin over the library index.
3. **The versioned project root and the document skills** — write-through `project/` in the
   backend (kind resolution, mounted-version check, the sync bridge to the document writer,
   turn-stamped rows, error strings), the plan card and inspector reading rows, retirement of the
   three tools, profile/skill/recipe grant, gate hand-off for ICPs, personas by the Head of ABM.
4. **Reads that page and spill** — pagination on the three reads, `read_claims@1`,
   `read_artifact@1`, the spill contract, W10 in the runtime, the `read_discovery_run` contract
   fix and the receipt-bound fix shipped first as a hotfix on the current tools.
