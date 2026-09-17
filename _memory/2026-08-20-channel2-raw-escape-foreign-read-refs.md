# 2026-08-20 — the sixth channel-2 escape: a foreign read reference, plus the class audit

Branch `platform/comprehensive-account-contact-research`. No commits made.

## Part 1 — the live defect (job `5b8898e3-aea7-5d36-b882-3bc319340454`, 06:40:41 IST)

**Symptom.** Three parallel `read_research_result` calls each raised
`EntityResearchToolAuthorityError("research result is outside the exact job")` raw →
`tool_failed` ×3 → `execution_failed` → job paused.

**Where the refs came from — answered from the live DB (read-only).** *Not* from a sibling job.
`read_account_research_state`'s `result_refs` is strictly job-scoped
(`AccountResearchStateStore._result_rows` → `WHERE request_row.job_id=:job_id`), so the state
surface advertises nothing foreign; there is **no** state-surface/read-tool inconsistency trap.
The three uuids (`cb0f2204…`, `047caa18…`, `06a15aa3…`) are rows in `claim`
(`core.employee_count`, `core.industry`, `core.hq_location`) — i.e. **`claim:<uuid>` references
out of the state projection's `existing_claims` block**, which the model re-prefixed as
`research-result:<uuid>`. Its own journalled reasoning says so: *"Let me try using research-result
with the claim uuid"*. The same turn had already been refused `reference_type_rejected` for
passing `claim:06a15aa3…` as a `parent_observation_ref`.

**Root cause.** `_model_supplied_uuid` only refuses a wrong *prefix*. With the right prefix and a
foreign uuid the parse succeeded, the row lookup missed, and the raw authority species escaped —
`_read_result_tool`/`_read_evidence_tool` catch **only** `EntityResearchGovernedRejection`
(commits `2d71e47f` → `85137024` → `6829ea94` → `b04eec41` built exactly that one path).

**Fix.** New `_foreign_read_rejection(...)` in `entity_research_tools.py` — both the result and
evidence "outside the exact job" raises now produce a subject-aware
`EntityResearchGovernedRejection("engine_authority_rejection", …)` whose detail keeps the original
sentence and names the two legal moves (read this job's own refs from
`read_account_research_state` / `read_contact_research_state`; a `claim:` or operation id is never
a read ref; otherwise proceed and finalize with the gap). The read authority is unchanged — no
foreign row is served.

## Part 2 — audit of the class

Rule applied (ratified): model-supplied input errors → governed recoverable refusal; money/truth
(unknown spend, fabrication, ledger tampering, cost mismatch) → keep suspending.

Converted (each with a red test):

| site | trigger | old → new |
|---|---|---|
| `entity_research_tools.read_result` foreign row | `result_ref` naming no/another job's result | raw `ToolAuthorityError` → `engine_authority_rejection` |
| `entity_research_tools.read_evidence` foreign row | same for `evidence_ref` | raw `ToolAuthorityError` → `engine_authority_rejection` |
| `read_evidence` offset past end / mid-code-point / `max_bytes` too small | model paging args | raw `ResultIntegrityError` → `evidence_page_rejected` |
| `contact_entity_research` all 7 tools | mistyped argument | raw `ValidationError` → `semantic_validation_error` (account parity) |
| `contact_engine_tool_bindings.repairable` | in-body `ValidationError`, escaping `GovernedRejection` | raw → rendered (account parity) |
| `reveal_contact_channel` / `validate_contact_channel` | any refusal | raw (no `repairable`, no `handle_tool_error`; they bypass `compose`) → rendered |
| `ContactResearchExecutionGuard` bad `channel` | invented channel name | raw `ValueError` → `ContactResearchAuthorityError` |
| `ContactResearchExecutionGuard` zero `field_keys` | `research_contact_deep`/`enrich_contact` with `[]` | reached provider → suspending integrity → guard refusal (mirrors account:1863) |

Deliberately **not** converted, and re-typed to the suspending species so the new channel wrapper
cannot render them: `contact_entity_research_channels._record_causation` (journal ref / causation
replay), `_fold_cost` (settlement replay, job/run budget overrun), `_projection` (post-settlement
row absent) — all now `EntityResearchResultIntegrityError`. Their *behaviour is unchanged* (they
suspended before, because those tools rendered nothing).

Left suspending, flagged: every `EntityResearchResultIntegrityError` on the provider persist /
causation / lineage path (engine truth); `EntityResearchFinalizationRejected` from
`{Account,Contact}ResearchFinalizationEngine.accept` — model-authored (the structured proposal)
but raised *after* the graph, outside `awrap_tool_call`, so it has no render path at all. That is
the one remaining model-triggerable failure class and needs an owner decision.

Steering: account manual v3 `read_research_result` / `read_evidence` refusal sections updated;
`evidence_page_rejected` added to the enforced `_ACCOUNT_MANUAL_REFUSALS` list.
