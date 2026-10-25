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
