# Free-flowing project documents (lane 1, task 7) — 2026-09-14

Founder ruling: the harness is not deterministic with a type, class or branch per narrow case. Any
markdown the agent writes under `project/` is a versioned document; the platform records and tracks,
it does not gatekeep by shape. "Is this the plan?" is a question the skill tells the agent to ask
the human, never code.

## What landed

- **One writer.** `arv2/project_documents.write_project_document(conn, storage, ProjectDocumentWrite(...))`
  — path-keyed replay id, project lock, revision check, front-matter stamp. `write_project_plan`
  stays as a thin wrapper (the retired-but-replayable `write_project_document@1` tool calls it, and
  it keeps `plan_document_id` so a replayed call lands on its own row). `write_project_persona`,
  `ProjectPersonaWrite`, `persona_path`, `persona_document_id`, `_persona_front_matter`, the
  `icp_not_pinned` check and `persona_front_matter_invalid` are **deleted** (no callers, no tests).
- **The stamp is six facts** — `version`, `status: ready`, `project_id`, `brand_id`, `authored_by`,
  `authored_at` — over the model's own front matter. `kind` is the document's word for itself
  (`document` when it claims none) and is NOT added to the front matter, only derived onto the row.
- **`project_root_writer`** refuses exactly two things: a compiled file (`compiled_file_read_only`)
  and a non-`.md` path (`unsupported_document_type`). `unknown_project_path`, the `_ICP`/`_PERSONA`
  regexes and the per-kind writers are gone. The outcome carries `title` (front matter `title`, else
  first heading, else file name).
- **Cards.** `PROJECT_DOCUMENT_OBJECT_TYPES` → one `PROJECT_DOCUMENT_OBJECT_TYPE`;
  `DomainObjectRef.title` and `VersionedWriteOutcome.title` (both defaulted, so stored receipts still
  validate); `conversation_turns._LEGACY_DOCUMENT_TITLES` keeps Plan/ICP/Personas for plan-3
  receipts only.
- **Role, not path.** `ProjectDocumentFacts` gains `role`/`title`, filled by
  `project_library._library_documents` (it already has the bytes); `render_status_markdown` picks the
  plan by `role: plan`, falling back to `project/plan.md`.
- **Every project document is human-editable** (`_EDITABLE_KINDS` deleted) and titled by its own text
  (`_TITLED_WITHOUT_THEIR_BYTES` deleted — one blob read per row now).
- **Migration `639d081ad799`** drops `brand_knowledge_document_kind` and
  `brand_knowledge_document_folder` (closed CHECKs that would have refused `kind: brief` /
  `folder: notes`). `path LIKE folder || '/%'` stays. Downgrade re-adds both and will fail loudly on
  a DB that has since stored a free document — deliberate.
- **ICP gate (P4-8).** `current_icp_document` already matched on front-matter `icp_key` (path was
  only a sort preference); the real narrowing was `kind = 'icp-definition'`, now dropped — one query,
  candidates ordered canonical-path → ICP-kind → path. `_ANSWERABLE_STATUSES` gained `ready`, because
  every agent-written document is born `ready` and the gate is the pin. `confirm_icp_document` still
  stamps `kind = icp-definition` on the confirmed version, so the human's yes is what promotes it.
- **Skills (bodies only, unpinned, founder review owed):** `plan-authoring/v2`, `icp-authoring/v2`,
  `persona-authoring/v2`, `stage0-interview/v33`, `manual-documents-decisions/v3`. No profile, no
  digest, no recipe — Task 5 mints those.

## Watch out

- `tests/agents/test_contracts.py::test_frozen_contract_json_schema_digests` was **already red at
  446e8f1db** (verified by removing the new field and re-running): ten frozen digests drifted before
  this task. Adding `DomainObjectRef.title` moves them further. Left untouched — the digest ritual
  needs whoever caused the earlier drift.
- Lane-DB data failures unrelated to this work: `test_the_project_scope_round_trips_down_and_up`
  (migration `b953bf11e2a9`'s downgrade re-adds the pre-`project-plan` kind CHECK, which three
  committed rows from the plan-3 live walk violate), `test_chat_gate_answers_o6_db` (two tests count
  `agent_gate_answer` rows globally; five committed rows from 09-11/12/13),
  `test_design_profile_resolves_with_the_full_granted_write_surface` (env model id),
  `test_production_context_s3_db` (two stale-source tests), `test_account_deep_fixture_a1`.
- A live walk of the new writer is owed (the lane stack was not driven for this task).
