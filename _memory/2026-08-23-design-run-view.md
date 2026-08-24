# 2026-08-23 — Design run view: the derived per-run observability surface (SHIPPED)

Plan: `docs/superpowers/plans/2026-08-23-design-run-view.md` (founder-ratified in-chat).
Commits: `ee25e9427` (plan) → `04ea7e606` + `727a343bd` (assembler + degrade fix) →
`2eef7eabf` + `59ccab8ff` (CLI + refusal hardening) → `530cd6e2c` (AGENTS.md §2a) →
`761d60928` (final fix wave). All task reviews + re-reviews + a whole-branch final
review clean; SDD workspace deleted after finish (this note + git history are the record).

## What exists now

`.venv/bin/python subsystems/clue-design/scripts/run_view.py <run_id|doc_id|leg_id>`
materializes `subsystems/clue-design/.design-runs/<ref>/` — manifest.json (run/leg/
document/counts/**gaps**), brief.json (the leg's frozen context bundle), scene.current.json,
envelopes/ (seq-ordered iteration record), events.jsonl (run_event stream), assets/
(symlinks, cache-preferred; `--copy` for real bytes), README.md. DERIVED, read-only,
disposable — never a fourth substrate (now enforced by a static no-write-SQL gate in
`test_run_view.py`, not just convention). Assembler: `lumen_api/run_view.py`
(`assemble(ref, *, database_url, asset_store_root, storage_fs_root) -> RunView`).

## Load-bearing facts learned (verified, not assumed)

- **`run_event.run_id` is NULL for every design row** (DB CHECK `run_event_subject_coherent`,
  migration `a02cbcb6e641`): design runs key on `subject_kind='design_run'`/`subject_id`.
- **The trio's INNER run id (what worker logs print) exists in NO durable table** — only the
  outer run's event payloads mention it. The CLI bridges it (bounded `strpos` scan over
  design_run-subject payloads, LIMIT 500 results, ambiguity warning, `bridged_from` in the
  manifest; the output dir keeps the asked-for name — trust `manifest["ref"]`).
- **Two durable key shapes**: scene assets `{ws}/design/{digest}`; a leg's
  `bundle_artifact_ref` is already a full `{ws}/{digest}` key.
- `/asset-store`'s LIVE-row predicate = `content_sha256` + `split_part(storage_key,'/',2)='design'`
  + both tombstone columns NULL, workspace-UNSCOPED (R-D4-7) — the view mirrors it read-only.
- `execution` is append-only (DELETE trigger) + workspace-FK'd → DB-seeded leg tests
  accumulate one execution+workspace pair per run (suite convention; conditional cleanup).
- Failed/stranded design runs' payloads carry no document id — a document-less failed run
  honestly gaps; there is nothing to recover (verified against the live stream).

## Controller rulings (undo targets if wrong)

1. **Inner-id bridge lives in the CLI, not the assembler** — a substring payload match is a
   paste-from-a-log affordance, not substrate truth; the assembler keeps its precision
   contract. Cost if wrong: programmatic callers wanting the bridge must shell out or lift
   `load_view`.
2. **Bridge is result-capped (LIMIT 500), not scan-capped** — finds older matches; unindexed
   `strpos` walks the design_run slice (cost measured acceptable on the dev stream, comment
   states it honestly). Cost if wrong: slow bridge on a huge stream → add a time/seq floor.
3. **Deferred (final-review triage, OK-TO-DEFER)**: digest-shape cosmetic guard; direct
   `design_agent_run`-lane + `durable_row=True` test coverage (fails loud, not silent);
   README.md's absence from the AGENTS.md layout list; bridge caveats in docs; matcher blind
   spots (`TRUNCATE x` without `TABLE`, `CREATE TEMP TABLE`) — two-word regex widenings if
   ever needed; `_reset` crash-window nit (refuses after a mid-reset kill; `rm -rf` and re-run).

## Future (founder items, not started)

- An inspector PAGE over the same assembler (designed UI → presentation-truth rule).
- Naming candidate runs in the doc-ref zero-events gap (`design_agent_run WHERE document_id=…`);
  a leg ref's `closed_by_run_id` could give events for free.
