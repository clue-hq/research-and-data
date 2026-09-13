# Lanes 1 and 2 — plan of action (2026-09-13)

**Founder decisions this index records:** three lanes run in parallel worktrees (workspace
reorganisation; gallery and document surface; telemetry). This index covers lanes 1 and 2. Lane 3
gets its own design doc first. One person drives all three, so "parallel" means separate
worktrees sequenced by dependency, never by owner.

## Lane 1 — the agent's workspace (this worktree, `research-streaming`)

| # | Plan | What it fixes / builds | Depends on | Grant |
| --- | --- | --- | --- | --- |
| 0 | `2026-09-13-read-tools-hotfix.md` | The five live-walk failures: the discovery read's output contract; the account read overflowing the 16 KiB receipt (paged by `offset` under a byte budget); a wrong prefix answered with the account's claim families; honest read refusals no longer spend the repair budget (W10) | nothing | skill v27 / profile v50 / recipe v26 |
| 1 | `2026-09-13-workspace-multi-root-backend.md` | The mount table on the backend; the `projects/<project>/{turns,threads}` layout; the persistent thread scratchpad with its own quota and retention; the `reads/` folder | 0 (nothing technical; sequencing only) | skill v28 / profile v51 |
| 2 | `2026-09-13-workspace-libraries.md` | Brand knowledge materialized once per version and mounted as `brand/`; the project library (status, decisions, current documents, artifact index) compiled from rows, digest-refreshed, mounted as `project/`; the turn pins the library index and replays from it; per-turn copies stop | 1 | skill v29 / profile v52 |
| 2b | *operating manual* (plan to be drawn from `docs/superpowers/specs/2026-09-13-head-of-abm-operating-manual-design.md`) | The builder and generated chapters (tools, fields, statuses, errors), drift tests, the capability-map block, `manual/` mounted, `manual@v1` pinned; path references added to the current skill. Hand-written chapters are drafted now, in parallel with plan 0, and founder-reviewed before this plan runs | 2 (the paths it cites settle there); the five founder decisions in the manual spec §9 | skill v30 (path references) / profile v53 / manual v1 |
| 3 | `2026-09-13-versioned-project-root-and-document-skills.md` | `write_file`/`edit_file` under `project/` land document versions through the existing writers (ICP, persona, plan); the plan card from the turn's rows; three document skills pointing at manual chapters; the three bespoke tools **and the three dead tools + `submit_ingestion@1`** ungranted; personas written by the Head of ABM; manual v2 (tool pages regenerated) | 2b | skill v31 + 3 skills / profile v54 / recipe v27 / manual v2 |
| 4 | `2026-09-13-paged-and-spilled-reads.md` | Pagination on every read; `read_claims@1`; `read_artifact@1`; oversized results spilled to `reads/` with a pointer receipt; `Literal` status types on the read outputs; the ICP fit-verdict read; manual v3 | 0, 1 (for `reads/`); 3 for the recipe number | skill v32 / profile v55 / recipe v28 / manual v3 |

**Run order:** 0 (+ two one-line fixes from the manual study: the stale surface framing sentence, the skill's onboarding pointer) → founder live walk of plans 1–4 of the 2026-09-12 set (27-item checklist) → 1 → 2 → 2b → 3 → 4. The manual's hand-written chapters are drafted alongside plan 0 and reviewed before 2b. Plan 4's Tasks 1–3 (pagination, `read_claims`, `read_artifact`) touch only `read_tools.py` and the toolbelt registration and may run any time after plan 0; only its Task 4 (spill) waits for plan 1's `reads/` folder.

**Lane-1 defect map (what each live-walk cause becomes):**

| Cause seen on 2026-09-13 | Fixed by |
| --- | --- |
| `read_discovery_run` fails its own output contract | plan 0 Task 1 |
| claims read exceeds the 16 KiB receipt | plan 0 Task 2 (byte budget + offset), plan 4 Task 4 (spill) |
| `overview_not_written` on a "Researched" account | honest; documented to the model in plan 0 Task 5's §7c; rendering the overview at research completion is an open product decision (spec §5) |
| a guessed `field_prefix` | plan 0 Task 3 |
| four refusals killed the turn | plan 0 Task 4 (W10) |
| no cross-thread continuity except through rows compiled per turn | plan 2 (library), plan 1 (scratchpad) |
| a bespoke tool per document; personas through an onboarding run | plan 3 |

## Lane 2 — the gallery and the document surface (new worktree, frontend only)

| # | Plan | What it builds | Depends on |
| --- | --- | --- | --- |
| 1 | `2026-09-12-plan-tab-frontend.md` (re-activated; Task 7 re-keyed on the plan part) | The Plan tab beside Gallery and Target accounts; the project document surface (react-markdown + CodeMirror, tokens only); auto-open when the plan is written; the plan card click; ICP and persona documents as gallery cards that open on the same surface | the plan-3 (2026-09-12) routes, already on this branch; nothing in Lane 1 |
| 2 | `2026-09-13-markdown-editor-toolbar.md` | The shared formatting toolbar and keymap over the CodeMirror editor, on the Knowledge editor and the document surface | Lane 2 plan 1 Task 5 |

**Run order:** 1 → 2. The worktree branches from this branch after Lane 1 plan 0 lands (so the
frontend sees the repaired read tools when walking the chat) and rebases over Lane 1 as it
merges; nothing in Lane 1 changes the document routes or the plan-part shape Lane 2 consumes.

## Where the lanes touch

- **Lane 1 ↔ Lane 2:** only the document routes (`GET/GET/PUT /frontend/v1/projects/{id}/documents…`) and the `plan` part with `planRef.objectType === "project_document"`. Neither lane changes them. When Lane 1 plan 3 makes agent-written ICPs and personas land as rows, Lane 2's gallery cards show them with no further work.
- **Lane 1 ↔ Lane 3 (telemetry):** both edit `agent_runtime_wiring.py` and the composition roots (`fleet_main`, `projections_main`, `head_of_abm_wiring`). Lane 3's first slice (OTel at the roots + one callback in the runtime's callback tuple) lands as a small early commit; Lane 1 plans 1–4 rebase over it.
- **Lane 2 ↔ Lane 3:** none.

## Verification that closes each lane

- Lane 1: each plan's final task is a live proof on the lane stack with SQL; the four owed memory notes gain "proven" sections; the reorganisation spec's §5 open questions are answered in the plan ledgers.
- Lane 2: browser checks with `/browse` on :3020 at the end of each task, plus the frontend gate; the gallery shows a project ICP card after Lane 1 plan 3's persona/ICP walk.
