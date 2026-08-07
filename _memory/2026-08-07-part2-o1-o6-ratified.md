# 2026-08-07 — Part II decisions O1–O6 RATIFIED (founder) — D1 unblocked

Founder ratified all six open decisions from `docs/specs/PD-part2-design-substrate.md` §6
(now updated in place — the doc is authoritative; this note is the session record + the
refinements' context).

- **O1** ✅ as recommended: `design_account.workspace_id NOT NULL`, `account_entity_id`
  NULLABLE, composite FK `(account_entity_id, workspace_id) → account_entity(id, workspace_id)`
  enforced when present. D3 wires resolve-or-create at the api root + decides NOT NULL.
- **O2** ✅ as recommended **+ promotion decided early: `design_brand_kit` IS the platform's
  versioned brand-kit payload** (closes the backlog's "no versioned brand-kit payload exists"
  gap; Part III's delegation bundle pins against it). Product vision recorded: per-workspace
  **brand studio** surface per brand — brand design-system tokens + the brand's asset store;
  founder has Figma screenshots (NOT yet captured into the repo — only a text attachment
  arrived; collect them at D3).
- **O3** ✅ clarified: drop ONLY legacy `asset_metadata`. `asset_descriptions` →
  `design_asset_description` ports **with full behavior**: AI generation, human-wins upsert,
  model attribution, caching, description stamping into versioned brand kits.
- **O4** ✅ as recommended: `X-Workspace-Id` header seam (401 absent) from first Postgres write.
- **O5** ✅ with a binding atomicity rule: bridge = `asyncio.run(dal_coroutine)` per op,
  connection bound to that op's loop; **atomic operations (e.g. lock-parent + allocate-seq) are
  ONE coroutine in ONE transaction — never several `asyncio.run` calls**. Bridge + daemon
  threads die at D5. **Founder FYI:** design deepagent may NOT ride the fleet (leaning, not
  committed); binding requirements regardless: restart-survivable runs + **multiple concurrent
  design-deepagent sessions** per user. D5 discussion re-opens the host question.
- **O6** ✅ slugs workspace-local: `design_web_publish` PK `(workspace_id, slug)`; global URL
  uniqueness = serving layer (Part IV). **O6b OPEN (ratify at D2):** interim rule for the
  now-ambiguous `/p/{slug}` route — (a) workspace in public URLs / (b) disable standalone
  public serving / (c) global public-route mapping. Recommendation on record: (a).
- **Append-only principle preserved (founder, same session):** the design history tables stay
  append-only with NO history-destroying compaction — undo writes forward envelopes, never
  truncates. D8 may address only DSAR/erasure reach + operational storage (partitioning/
  archival), never silent history loss. §8 of the contract doc now states this as a principle.

**State:** D0 committed (`fb2fe88d`); O1–O6 ratified with O6b the only open sub-decision
(gates D2, not D1). **D1 is unblocked** — next session: implement the six `design_*`
migrations off `c6d84aa84b79` per §5/§7 of the contract doc, after the user gives the D1 go.
Still pending separately: the 23-file ruff-format drift ruling (`make lint` red at origin/main).
