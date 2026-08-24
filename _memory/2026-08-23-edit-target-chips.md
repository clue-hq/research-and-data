# 2026-08-23 — platform edit-target chips (closed)

User-authorized slice: selected scene nodes become typed, version-pinned
`design_node` context refs beside the open leg's `design_document` ref; the
platform validates them before acceptance, freezes them durably, and translates
them into the design runtime's existing `target_node_ids` plus a server-derived
active page. Frontend chips mirror `sceneSession.selectedIds`; submission must
snapshot the ids before any async wait.

Initial findings: P3 already persists ordered context refs and the scene runtime
already consumes target ids. The missing joins are the context vocabulary/DB
CHECK, open-leg + exact-scene validation, envelope translation, and composer UI.

## Implemented

- Added `design_node` to the typed turn-context wire contract and to the durable
  context-ref table CHECK via Alembic revision `54ae25174405` (single head).
- New submissions validate one exact-version scene document against the thread's
  open design leg, resolve every ordered target node in that scene, and require
  all targets to be reachable from one server-derived page. Idempotent retries
  compare their immutable durable receipt before consulting mutable document
  state, so a later edit does not invalidate an already accepted turn.
- The design-leg envelope translates only those durable `design_node` refs into
  `request.target_node_ids` and derives `request.active_page_id` from the
  server-side scene. The original refs remain ordered in `leg.focus_refs` and
  `agent_turn_submission_context_ref` for transcript inspection and replay.
- Project chat now renders removable chips from `sceneSession.selectedIds` and
  the live scene's node labels. Removal delegates to the existing additive
  selection reducer, preserving Shift/Cmd multi-selection semantics.
- Submission copies selected ids synchronously, then drains optimistic writes
  and stamps the latest acknowledged document version. A visible target that
  cannot be tied to a version fails closed through the existing editor error
  line instead of silently submitting an unfocused turn.

## Verification

- Frontend: 2,008 tests passed; ESLint passed with the two pre-existing unused
  snapping-helper warnings; Next.js production build and TypeScript passed.
- Backend changed scope: 12 pure validation/context tests passed; focused runtime
  state and targeted-edit acceptance tests passed; ruff and targeted mypy passed.
- Root gates: formatting, ruff, mypy (727 files), and all 26 import contracts
  passed. Alembic reports one head: `54ae25174405`.
- The optional Postgres acceptance fixture was unavailable, so the new route and
  envelope DB tests were collected but skipped. `make test` was stopped after
  341 passes / 62 skips at the pre-existing O3 fixture failure: it requests
  `account-deep-steering@v4`, which the current v39 profile does not disclose.
- User-owned untracked screenshots and screen recording under
  `docs/specs/ad-editor-integration/` were not touched.

Local commit message: `feat(design-editor): bridge selected nodes into design turns`.
