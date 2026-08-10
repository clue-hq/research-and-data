# 2026-08-10 — R2 atomic Home project bootstrap

## Scope completed

- Implemented **R2 only** from the ratified chat-integration recovery plan: the Home composer now reads a real workspace-scoped bootstrap contract and one submit atomically creates an `Untitled project`, derives the first thread title from the user's message, captures the message, emits `turn.accepted`, and queues the existing platform-Deep-Agent turn task.
- Did not begin R3. Project-shell reads, the empty new-project Gallery, project catalog/sidebar data, and hamburger hover/click behavior remain R3-owned. The browser therefore still joins the real R2 project/thread to the existing fixture-backed project title and Gallery surface.

## Backend changes

- Added `project.write` to auth policy revision 2. Operators/admins/owners receive it; viewers stay read-only.
- Added strict Home request/response and bootstrap wire models.
- Added `GET /api/v1/home` with scoped real brands, deterministic suggestions, and explicit false capabilities for context refs, attachments, and agent-profile selection.
- Added `POST /api/v1/projects` when durable artifact storage is composed. It requires `project.write`, `thread.write`, and a nonblank `Idempotency-Key`; validates the brand in the active workspace; rejects unsupported controls honestly; serializes concurrent retries with a transaction-scoped advisory lock; and creates/project-thread-capture-submission-event-queue inside one connection transaction.
- Project identity, thread identity, and turn identity are deterministic per workspace/idempotency act. Exact replay returns the same identities with HTTP 200; conflicting reuse returns `IDEMPOTENCY_CONFLICT`.
- `clue_spine.create_project` now accepts a typed status so Home bootstrap can create the project directly as `active` while preserving the existing `draft` default.

## Frontend changes

- Added Home wire and bootstrap Zod schemas plus fixture/HTTP repository adapters on the existing transport seam.
- HTTP Home no longer renders fixture bootstrap data while loading. The controller fetches `/home`, submits exactly one `/projects` request, retains one idempotency key for same-input retry, and navigates only to the backend-returned `href`.
- Unsupported attachment, context-reference, and profile/model controls are hidden. Brand selection is shown only when required by the real catalog.
- The long message-derived thread title exposed a header overflow during browser verification. The thread selector now has a bounded flex width, ellipsis, preserved full option text, and an accessible name; action buttons keep their own width.

## Verification

- Backend focused acceptance: `8 passed` (`tests/auth/test_policy.py`, `tests/api/test_home_project_bootstrap_db.py`) against the isolated migrated Postgres database `clue_r2_damascus_20260810`.
- Backend chat/spine regression: `36 passed`.
- HTTP gateway isolation: `2 passed`.
- Ruff: passed for every changed backend/test file.
- Frontend: ESLint passed; `tsc --noEmit` passed; full unit suite `115 passed`; design-system token build passed.
- A production `next build` was deliberately stopped after the optimizer remained idle while the live `next dev` process owned the same `.next` workspace. The live server was preserved for browser verification; no build success is claimed.
- Browser Home loaded the real workspace contract with three backend suggestions and no unsupported controls. One submit of `R2 browser verification: reply in one sentence confirming this new project context.` navigated to `/projects/prj_3396a3da360e5db08dd915ee988af54a?thread=thr_4afa9d5342395e579ee873d356cfdc60` without prompt/model/entity query leakage.
- Read-only DB join proved: `Untitled project | active | R2 browser verification: reply in one sentence confirming this new project… | 800538cc-8fc5-52a7-b77e-7a0e76d54a7d | turn.accepted | agent_turn`.
- The isolated browser database has no fleet worker attached, so the accepted task remains visibly queued; this is queue durability evidence, not an R2 execution failure.
- Post-fix DOM measurement: selector right edge `370px`, conversation-pane right edge `480px`, Gallery left edge `492px`; the selector is contained with `122px` clearance to Gallery.

## Runtime and preservation notes

- The shared `clue` database was not migrated or modified after it proved to be missing the current auth schema. Browser verification used the isolated R2 database and a disposable filesystem artifact root instead.
- The isolated backend and live frontend were left running so the finalized browser tab remains inspectable.
- User-owned untracked `.artifacts/` was not changed or staged.
