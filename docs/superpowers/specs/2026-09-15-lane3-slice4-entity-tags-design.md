# Lane 3 slice 4 — entity tags on traces — design

**Status:** approved in chat 2026-09-15 (D1 tags plus metadata; D2 the job tags its subject and
what it wrote); executed 2026-09-15. Parent: the telemetry and cost design note
(`2026-09-14-telemetry-and-cost-observability-design.md`, §5.3 "Entity tagging", §6, §9 slice
4). Rulings R5 (erasure reachability), R11 (legacy lane untouched), R13 (the erasure lane owns
deletion). Builds on slice 3 (`2026-09-15-lane3-slice3-langfuse-design.md`).

## 1. Purpose

After this slice, "every trace that carried contact X" is one Langfuse query. The two kinds of
trace that carry personal claims — the research job that wrote them and every chat turn whose
read tools served them — are tagged with the entity ids they wrote or served, on the trace
itself, so ARV2's erasure (D10, the R13 lane) can find and delete them, and an operator can do
the same by hand until then. Nothing is deleted here; no new env, no migration; a no-op when
Langfuse is off.

## 2. What exists (verified 2026-09-15)

- `clue_obs.langfuse.propagate_trace` wraps the SDK's `propagate_attributes`; the SDK **merges**
  nested propagation (an inner `propagate_attributes(tags=..., metadata=...)` adds to the outer
  tags and metadata for spans opened inside; probed 2026-09-15: outer `("a",)` + inner
  `("b",)` → the inner span carries `("a", "b")` and both metadata keys). `event(name, ...)`
  opens a closed span under the current one. `current_ids()` gives the current trace id.
- The research job runs under `observation("arv2.account_research", as_type="agent")` inside
  `propagate_trace(...)` (slice 3b) with `runtime.scope` (`account_id`, `contact_id`,
  `subject_kind`). `_write_claims` builds drafts with `agent_claims(...)` (each `ClaimDraft`
  carries `entity_id`) and writes them through `runtime.write_each(drafts)`. The committee
  step (`committee_step.run_committee_step`, called by the driver right after
  `run_account_agent` in the same task) mints each member's `contact_id` and writes
  `committee_member_claims(...)` for it; the on-demand person launch
  (`account_research_launch.py`) writes the same claims for a launched person.
- The turn's ARV2 read tools (`arv2/read_tools.py`): `ReadAccountResearchTool.invoke` serves
  one account (`research.account_entity_id`); `ReadClaimsTool.invoke` serves one entity
  (`page.entity_id`, `page.entity_type` in {account, contact}). Both run inside the turn's graph
  (the `head-of-abm.turn` trace). `ReadProjectAccountsTool` lists accounts and serves no claims.
- Langfuse trace filters: tags match exactly; metadata filters by key and value.

## 3. Design

### 3.1 `clue_obs.langfuse.tag_entities`

`tag_entities(entity_ids: Iterable[str]) -> None`:

- keeps one accumulator per trace in a `ContextVar[tuple[str, set[str]] | None]` — the trace id
  it belongs to and the ids seen so far; a call whose current trace id differs from the
  accumulator's (or with no accumulator) starts a fresh set. The context variable is set, never
  reset, so it survives the `propagate_trace` block and reaches the driver's committee step in
  the same task;
- unions the new ids in, then emits one `entities.tagged` event inside
  `propagate_attributes(tags=[f"entity:{id}" for id in sorted(all)], metadata={"entities":
  ",".join(sorted(all))})` with `output={"entities": sorted(all)}`. The **whole** set is
  re-emitted every time, so the trace ends up right whether Langfuse merges trace attributes by
  union or by last writer, and the SDK's own merge keeps the outer trace name, session, user,
  role and lane tags on that span;
- is a no-op when Langfuse is not installed, when no trace is current, or when the ids are empty
  after dropping blanks. Ids are stringified; duplicates collapse.

**D1 (ruled):** both forms — `entity:<id>` tags (exact-match filter) and the `entities` metadata
list (contains filter) — so the erasure query works either way.

### 3.2 The research job (D2)

- `run_account_agent`: right after the agent observation opens, `tag_entities([scope.account_id]
  + ([scope.contact_id] if scope.contact_id else []))` — the subject.
- `ToolRuntime.entities_touched: set[str]` (new, empty). `write_each` adds every draft's
  `entity_id` it was asked to write (before writing; a failed draft still named the entity the
  job was working on). `_report_ending` is followed by `tag_entities(runtime.entities_touched)`
  inside the observation, so every entity the job wrote claims about is on its trace.
- `committee_step.run_committee_step`: when a member is inserted, `tag_entities([contact_id])`
  beside the `committee_member_claims` write, so the members born after the agent finished are
  on the job's trace too (same task, same accumulator). The on-demand person launch does the
  same at its `committee_member_claims` write (it runs in an API request; the tag lands on that
  request's trace).

**D2 (ruled):** the job tags its subject and what it wrote, not what its own tools read: the
job's reads concern its subject already, and tagging every returned entity adds noise and
nothing for erasure.

### 3.3 The read tools in a turn

- `ReadAccountResearchTool.invoke`: after the service returns, `tag_entities([research.
  account_entity_id])`.
- `ReadClaimsTool.invoke`: after the service returns, `tag_entities([page.entity_id])` (an
  account or a contact — whatever the rows resolved).
- `ReadProjectAccountsTool` is not tagged (no claims served; a page can hold 100 ids).

### 3.4 The erasure hook (R13)

The parent note's §6 gains the exact query: traces where tag `entity:<id>` is present (or
metadata `entities` contains `<id>`), then delete through the Langfuse API and record the deleted
trace ids in the erasure audit. That is the step ARV2's erasure (D10) runs; the pilot's manual
posture uses the same filter in the UI.

## 4. What does not change

- No legacy research-lane file (R11), no design-subsystem file (R12), no frontend file.
- No migration, no new env, no new observation types; the agent tree of slice 3 is unchanged
  except for the added `entities.tagged` events.
- The read tools' outputs and refusals; the job's rows, receipts and endings.

## 5. Testing

Offline, with `tests/_langfuse.py::langfuse_installed()`:

- `tests/test_obs_langfuse.py`: not installed → `tag_entities` is a no-op; installed → two calls
  inside one trace emit two `entities.tagged` events, the second carrying the union as tags and
  as the `entities` metadata, with the outer trace name and tags preserved; a new trace starts a
  fresh set; blanks and duplicates are dropped.
- `tests/arv2/test_account_research_agent_langfuse.py`: a finalized job's trace carries
  `entity:<account id>` (the subject) and, after a `write_claims` call in the scripted run, the
  written entity ids from `runtime.entities_touched`; a person job carries the contact id.
- `tests/arv2/test_read_tools_langfuse.py`: `ReadAccountResearchTool` and `ReadClaimsTool` over
  a fake `Arv2ReadService` emit an `entities.tagged` event naming what they served; a refused
  read tags nothing; off → nothing.
- `tests/arv2/test_committee_step*.py` (existing harness): an inserted member tags its contact
  id (extend the existing DB test with `langfuse_installed()` if the harness allows; otherwise a
  unit test over the write seam).
- Live proof (founder-triggered): after one turn that reads an account's claims, the turn's trace
  in Langfuse shows the `entity:<account id>` tag.

## 6. Deferred

- The erasure itself (D10, R13) and the operator step of setting the Langfuse project's
  retention for the pilot (still owed from slice 3).
- Non-graph gateway completions (value narrative, exit judge, Stage-0 extractor, judges) and the
  old lane's Sumble and Exa tier-3 provider calls remain off the Postgres ledgers (founder ruling
  2026-09-15: leave as is); recorded in the parent note's §8.
