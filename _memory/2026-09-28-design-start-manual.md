# Native design-start guidance — 2026-09-28

- Continued the trace-led native website goal. Found current Head-of-ABM prompt
  v13 teaches automatic generation, but tool descriptor/manual v8 still teaches
  waiting for another user message. The runtime already queues the initial turn.
- Updated descriptive tool text and minted manual v9 / profile v62 through the
  catalog generator, exact hashes and both active selectors. No schema, grant,
  model, cap, prompt, provider or execution behavior changed. Old versions intact.
- Four generated chapters match; all 15 pins verified; parsed profile comparison
  confirms only manual refs and version differ. Scoped Ruff/format/whitespace pass.
- Agent/catalog/registry/privacy/contract suite: 418 passed, 4 skipped, one existing
  missing-refusal-note failure. Reproduced that same failure using HEAD notes and
  unchanged v61: invalid_page and overview_metadata_too_large in read-tools v3.
  Do not add misleading errors to the v2 grant just to silence module-wide scan.
- DB agent runtime and design-entry tests: 12 passed on a newly-created disposable
  DB; automatic queue, replay and no-submission behavior covered. Migration
  up/down/up also passed there. No live DB migrated. Root make check stops on
  formatting in unrelated untracked test_seller_context_db.py, left untouched.
- User approved one new native draft after the pending scoped question ("sure go
  ahead"). Next: refresh only owned idle services, submit one simple account
  request in fresh Conduit, inspect current result and traces before any rerun.
  No new page submitted at this checkpoint. No remote push/publication.
- Initial commit check found existing generator-style blank lines at EOF in the
  new generated chapters/profile. Preserved generator bytes and exact hashes;
  checked other whitespace with only blank-at-EOF warnings excluded.
- Disposable database removed after successful checks; live database unchanged.
