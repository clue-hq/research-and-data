# Direct Mail frontend implementation

- Founder authorized building the presented flow. Follow existing Clue theme,
  simple standard layouts and shared controls; no decorative dashboards or AI badges.
- Plan: `docs/superpowers/plans/2026-10-25-direct-mail-frontend.md`.
- Worktree/branch unchanged: `feat/direct-mail-infrastructure-ui`; server 5000.
- Ruling: execute inline using existing authorization; no additional confirmation
  round for the implementation plan. One fresh whole-branch review at the end.
- Data boundary: explicit preview provider; synthetic data and local uploads,
  no actual order/research/carrier actions. Production paths remain unavailable.
- Ruling: use IndexedDB for atomic records + uploaded assets so reloads/tabs
  share versioned drafts without embedding mock state in presentation.
- Task 1 in progress; no Direct Mail implementation committed yet.

## Customer UI checkpoint

- Domain/repository committed at c481db10d and ed50e2523. Customer screens,
  licensed preview fonts and shell/chat/Gallery entry points at e55fae61d.
- Browser verified individual gift → card → address → approval → tracking;
  reload retains approval. Bulk select of 8 records included only the one
  reviewed/ready record; successful result identified the recipient.
- Uploaded sample PNG through the real file picker; saved card renders and is
  marked pending production validation. Narrow viewport has no document overflow.
- Full frontend suite: 3648 passed, 5 skipped, zero failures before final font
  error regression addition. Required design build passed; lint initially caught
  a sidebar data-layer import, fixed through a controller hook. Lint now has only
  11 existing warnings; production build passed.
- Raw tsc --noEmit reports pre-existing design-editor test type errors; no new
  Direct Mail errors appeared. One un-escalated tsx run failed on sandbox IPC;
  rerunning with the usual sandbox permission worked.
- Fixed address attention clearance and replacement stale shipment/photo state
  with failing regression tests first. Missing handwriting now surfaces an error
  instead of silently rendering a fallback; focused suite now has 13 tests.
- Handoff documents explicit adapter replacement and live contract review.
  Initial campaigns use prepared synthetic recommendations; actual research job
  and incomplete-proposal projections remain a backend integration slice.
- No production mutations, remote pushes or 3000-series changes.
