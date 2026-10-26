---
schema_version: "1"
kind: skill
name: manual-workspace
version: v23
summary: "Manual: your folders and mounts, the project's attachments, every card the turn places for you, and how ls, read_file, glob, grep and edit_file really behave."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
<!-- sources: research/2026-09-13-head-of-abm-manual/B-context-and-workspace.md §2 and §3 (paths as the workspace libraries land them); research/2026-09-13-head-of-abm-manual/A-tools.md §8-9 (the framework file tools); code: platform/api/clue_api/project_context_files.py ProjectLibraryIndexCard (the project library index card plan 2 composes in place of the project files index) -->
# Your workspace: what is where, and what you may do to it

One workspace directory per chat thread, with one live lease at a time, so two turns of the
same thread never write over each other. Everything you read and write is a relative path
inside it. There is no host filesystem, no shell and no network here.

| Folder | You may | What it is |
| --- | --- | --- |
| `attachments/` | read | every file anyone has attached in this project, under its own filename. Read only. |
| `brand/` | read | the brand library: what the platform researched about this brand. Read only. |
| `project/` | read and write | this project's library, shared by every thread of the project. Three paths under it are yours to write; the rest is compiled. |
| `inputs/` | read | this turn's human message and the refs attached to it. Rewritten every turn. |
| `context/` | read | the cards the turn composed for you. Rewritten every turn. |
| `scratch/` | read and write | your notebook. It persists across the turns of this chat and nobody else reads it. |
| `reads/` | read | reserved for platform written spilled reads. It arrives with a later plan; nothing writes there today. |
| `work/` | read and write | scratch inside one turn. Nothing is persisted from it. |
| `outputs/` | read and write | the turn's durable product. Saved as artifacts at finalize and kept here for this chat's later turns, until the workspace is cleaned 24 hours after the chat's last turn. Check a file is there before relying on it. |
| `.deepagent/` | read | your own manifest, profile, prompt and skills, including these manual chapters. |

Writes are allowed only under `scratch/`, `work/`, `outputs/` and `project/`, only with the
extensions `.json`, `.md`, `.txt` and `.yaml`, and only inside the quotas in `.deepagent/skills/manual-limits/v23/SKILL.md`. A write
outside those prefixes is refused `permission_denied`. `project/` is the versioned root: a write
there lands a new version of the document the path names and refreshes the file you read back.
Which three paths are writable, and what every other path refuses, is in
`.deepagent/skills/manual-documents-decisions/v23/SKILL.md`. You still cannot edit a brand
knowledge file with your file tools: `brand/` is read only. When the person asks for a change,
`write_brand_document` publishes a new version, and it appears under `brand/knowledge/` on the
next turn.

A script run by `run_python` sees the same tree at `/workspace` and answers to the same rules,
with two differences. It may write the formats your own `write_file` may not — `.csv`, `.xlsx`,
`.docx`, `.pptx`, `.pdf` and `.png` — because producing those files is what the sandbox is for.
And it writes under `scratch/`, `work/` and `outputs/` only: `project/` is read-only to a script,
so a project document is still written with `write_file`. Everything a run leaves behind is
checked against this policy the moment it exits, and a file outside the extensions, over the
per-file ceiling, or over the quota is deleted; the result's `files_written` and `files_removed`
say what survived and what went. How to write the script is
`.deepagent/skills/code-execution/v1/SKILL.md`.

## `attachments/` — every file attached in this project

- One folder, one copy per file, at `attachments/<filename>`. Every file anyone has attached in
  any thread of this project is here, not just the ones attached to this turn; the turn's message
  names the ones attached to it, with the path and the tool that opens each.
- Nothing here is a summary, a conversion or an extract. It is the file itself, exactly as it was
  uploaded. Nothing else in your context describes its contents, so a file you have not opened is
  a file you have not read.
- A text file — `.md` or `.txt`, and a small `.csv` or `.json` — opens with `read_file`.
- A PDF, a Word file, a PowerPoint deck, an Excel workbook, an image, and any text file over the
  per-file read ceiling open with `run_python`. `read_file` refuses them: over the ceiling is
  `quota_exceeded`, and bytes that are not UTF-8 text are `permission_denied`.
- The folder is read only, for you and for a script. It is also absent from a project nobody has
  attached anything to, which is the ordinary state of a new project; `ls` shows it when it
  exists.

The recipes for opening each kind of file, and the rules about what you may say afterwards, are
`.deepagent/skills/code-execution/v1/SKILL.md`.

## `brand/` the brand library

- `brand/knowledge/<folder>/<file>.md` holds the documents: `company/overview.md`,
  `product/catalog.md`, one `product/<slug>.md` per researched product,
  `proof/customer-reviews.md`, `audience/icp-<key>.md`, `audience/persona-<key>.md`.
- `brand/index.json` is the manifest. One line per file with its path, kind, version, status,
  a one line summary, and the document's digest. It also names this project's confirmed ICP
  and its confirmed product set.
- If the manifest lists no documents, onboarding has not produced knowledge for this brand
  yet. Say so plainly. Onboarding runs from the workspace's onboarding flow, not from a
  control on the Knowledge page; see `.deepagent/skills/manual-humans-screens/v23/SKILL.md`.
- When two versions of one path are pinned, the pinned version keeps the plain name and the
  other carries its version, such as `audience/icp-gi.v3.md`.

## `project/` the project library

- `project/status.md` is compiled from the rows every turn: confirmed ICP, products, plan,
  accounts, discovery, research, personas, project documents. Every section is always present;
  an empty one says so in words.
- `project/decisions.md` is what the human told this project, in their own words, one line per
  recorded decision.
- `project/plan.md`, `project/audience/icp-<key>.md` and `project/audience/persona-<key>.md`
  are this project's own documents, and the three paths you write.
- `project/artifacts/index.json` lists the gallery's artifacts by reference.
- `project/index.json` lists the library's files.

Every thread of this project sees the same library, so what another thread settled is here.
The library is compiled once per turn and pinned, so it does not move under you while you
work. What the words in `status.md` mean is `.deepagent/skills/manual-accounts-research/v23/SKILL.md` and `.deepagent/skills/manual-discovery/v23/SKILL.md`.

## `inputs/` this turn

- `inputs/user-message.txt` is the human's captured message, verbatim.
- `inputs/current-context/<ordinal>-<type>-<id>.txt` is one file per subject the human attached
  to this message, in their order. Words like "selected", "this", "these" and "them" name
  exactly these refs. Never widen them, never replace them, and never ask the human to retype
  them.

## `context/` the cards

Card file names under `context/focus/`, `context/memory/` and `context/workspace-product/`
carry a hash you cannot derive from an id, so list the folder rather than guessing a path.

| Card | What it carries |
| --- | --- |
| `context/project/project_card.json` | project id, name, status, workspace, brand, the single confirmed product pin (usually null, because a project here targets a set), the thread id, and a `context_availability` block. |
| `context/project/budget.json` | `limit_millicents`, an `external_research_budget_cents` literal, and a scope sentence. |
| `context/project/brand_knowledge_index.json` | the brand document index, the project's confirmed ICP reference, and the confirmed product set. Present only when at least one brand document is pinned. |
| `context/project/project_library_index.json` | the manifest of the `project/` mount you are reading: one line per file with its path, its workspace path, kind, version, status, a one line summary and the digest of the bytes installed there, plus the digest of the whole generation and how many artifacts `project/artifacts/index.json` names. It is the same manifest the mount serves as `project/index.json`. |
| `context/focus/*` | the hydrated row for each attached account, contact or project. A contact card is deliberately minimal: name, title, persona, account name, account domain. |
| `context/workspace-product/*` | the brand row, and the product row when one is pinned. |
| `context/memory/*` | advisory preferences and learnings, when any are selected. |

Two honest warnings about those cards:

- `context_availability` always reads `client_knowledge: unavailable`,
  `stage0_project_state: unavailable`, `brand_profile: minimal`,
  `product_profile: unavailable`. That is a stale field, not a statement that you have no
  knowledge of the client: the knowledge is in `brand/knowledge/`. Do not tell the human you
  have no client context because of it.
- The budget card's `external_research_budget_cents` is a hardcoded `"0"` and its scope
  sentence predates the launch tools you hold. It is not a burn down and it is not a fact about
  what has been spent. What the number does enforce is in `.deepagent/skills/manual-gates-authority/v23/SKILL.md`.

For more about an attached account or contact than its focus card carries, use
`read_account_research`, in `.deepagent/skills/manual-tools/v23/SKILL.md`.

## The file tools, as they really behave

They are framework tools, not governed ones: no receipt, no journal row, no replay. Their
errors are plain strings, listed in `.deepagent/skills/manual-errors/v23/SKILL.md`.

| Tool | What to know |
| --- | --- |
| `ls(path)` | a flat file walk. `is_dir` is always false, for every entry, always. There are no directory entries in a listing. The root is allowed. |
| `read_file(file_path, offset, limit)` | `offset` and `limit` are in **lines**, not bytes. The default window is the first 2,000 lines. A file over the per file byte quota is refused, not truncated, and a file that is not UTF-8 text is refused too — both open with `run_python` instead. Batch your reads: issue the reads you need in one step. |
| `write_file(file_path, content)` | whole file replace, under a writable prefix and an allowed extension only. |
| `edit_file(file_path, old_string, new_string)` | the source text must appear exactly once. Zero matches and more than one match are both refused. `replace_all=true` is in the schema and is refused outright. |
| `glob(pattern, path)` | plain filename matching over a flat list, not path globbing. `*` crosses `/`, and `**` is just two stars. |
| `grep(pattern, path, glob)` | a plain substring test, not a regular expression. It reads every matched file whole, so one oversized file fails the whole scan. |
| `write_todos(...)` | the framework's own scratch plan. It writes nothing durable. |

## `outputs/` and the end of the turn

Everything under `outputs/` is read at finalize, persisted as artifacts, and the tree is
frozen; after that the folder is immutable and a write to it is refused `conflict`. The
finalization refuses if the outputs differ from that frozen snapshot, so do not plan to write
there after you finalize.
