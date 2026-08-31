# Design Subsystem Integration — Master Plan of Action

**Status:** ADOPTED — 2026-08-03. This is the authoritative, self-contained plan for unifying the design subsystem repo (`clue-design` / *havana*) with the platform repo (`research-and-data`) and integrating the design deepagent into the platform deepagent, end to end.
**Routing decision (final):** the design deepagent is integrated as a **LangGraph-wrapped subagent with an in-graph human-in-the-loop (HITL) node**. Routing between the user and the active agent is a property of **graph state** — the interrupted graph receives the next message. There is **no UI-driven routing**: no button, no surface-focus rule, no clickable toggle decides who answers. The only UI element related to speaker identity is a passive, display-only indicator.

---

## 1. What we are building, in one paragraph

One product, one session. A user strategizes their ABM motion with the platform deepagent and, in the same chat thread, asks for a design ("draft a LinkedIn ad for this target account"). The platform deepagent routes the task to the design deepagent — a subagent wrapped in its own LangGraph. From that point the user talks **directly** to the design deepagent, iterating on the design to-and-fro (including canvas interactions: selecting a node puts it in the agent's context), until the user locks the design — or asks something outside design scope — at which point the graph reaches its END node, the design leg closes, and the platform deepagent takes over again with a summary of what was produced. The user never leaves the thread, never clicks to switch agents, and never repeats themselves.

The plan has four parts, executed in order, with explicit gates:

- **Part I** — Repo unification (monorepo merge with full history preservation).
- **Part II** — Substrate adoption (tenancy, Postgres, storage, execution) for the design subsystem's backend.
- **Part III** — Agent integration (the graph-wrapped design subagent under the platform deepagent).
- **Part IV** — Surface integration (the editor mounted in the platform frontend, feeding canvas context into agent turns).

---

## 2. Target agent architecture (the adopted design)

```
user ⇄ [one chat thread]
         │
         ▼
   Platform DeepAgent  ──────────────► research subsystem, discovery,
         │                              scoring, other subagents/tools
         │  delegates design leg
         ▼
   ┌───────────────────────────────┐
   │  Design leg — LangGraph        │
   │                                │
   │   Design DeepAgent  ◄──┐       │
   │        │               │       │
   │        ▼               │       │
   │   HITL node (interrupt)┘       │   ← user messages resume HERE,
   │        │                       │     flowing straight to the
   │        ▼                       │     design deepagent
   │      END                       │
   └───────────────────────────────┘
         │  on END: summary + refs
         ▼
   Platform DeepAgent (resumes ownership)
```

Three nodes inside the design leg's graph:

1. **The design deepagent** — the existing design agent (orchestrator + DSL author + visual reviewer trio, virtual workspace, round history, propose→Accept/Reject turn shape), unchanged in its internals.
2. **The HITL node** — a LangGraph `interrupt`. After the design deepagent produces a proposal (or a clarification question), the graph pauses here, awaiting the user. The user's next message **resumes the graph at this node**, which hands the message directly to the design deepagent. This is what makes iteration direct: while the leg is open, no user message passes through the platform deepagent, costs a relay hop, or loses fidelity.
3. **END** — closes the leg. Reached on exactly two triggers, both invoked by the design deepagent itself (see §2.2).

This whole graph attaches to the platform deepagent as a **subagent**. The platform deepagent starts a leg by delegating to it; the leg's interrupted state *is* the routing state. "Who answers the next user message" is answered by one rule with no exceptions:

> **The innermost interrupted graph receives the next message. If no graph is interrupted, the platform deepagent receives it.**

### 2.1 Leg lifecycle

1. **Delegation.** The user asks for a design. The platform deepagent invokes the design subagent with a **context bundle** (§2.3). The graph starts; the design deepagent runs its first round and produces a proposal (or a clarification question). The graph reaches the HITL node and interrupts.
2. **Iteration loop.** Every user message now resumes the graph at the HITL node → design deepagent → new proposal / response → interrupt again. Canvas interactions ride along: node selections, active page, and the target document reference are attached to each turn (§2.4). This loop runs as many rounds as the design needs.
3. **Exit — lock-in.** The user signals the design is done ("lock it in", accepts the final proposal). The design deepagent calls the structured exit tool with `reason=locked`; the graph transitions to END.
4. **Exit — out of scope.** Mid-session, the user asks something that is not design (ABM strategy, campaign questions, account questions). The design deepagent recognizes this and calls the exit tool with `reason=out_of_scope`. The graph transitions to END, **and the triggering user message is re-delivered to the platform deepagent** together with the leg summary — the platform deepagent answers the question immediately; the user never repeats themselves.
5. **Return.** In both exits, the subagent returns a **summary + references** to the platform deepagent — final document version, accepted operations, open gaps — never the design transcript. The platform deepagent's context stays clean; the full design history remains on the shared thread and in the leg's durable state.

### 2.2 The structured exit contract (engine disposes)

END is reachable **only** through an engine-validated tool call:

```
finish_design_leg(reason = locked | out_of_scope | abandoned,
                  summary_refs = {document_version, accepted_ops, open_gaps},
                  pending_user_message? )   # required when reason=out_of_scope
```

Rules, per the house "agent proposes, engine disposes" discipline:

- The design deepagent can never end the leg by free-text inference or by simply stopping; the engine validates the call shape and journals the decision.
- `out_of_scope` **requires** `pending_user_message` — the engine re-delivers it to the platform deepagent on leg close.
- A **mis-exit is cheap to undo**: the leg's graph `thread_id` and checkpointed state persist after END. If the user says "no, go back to the design," the platform deepagent re-delegates with the same leg id and the graph **resumes** — canvas state, round history, and conversation context reopen exactly where they were. No work is lost by a wrong exit; this is the safety property that makes agent-decided exits acceptable without any UI fallback.
- The exit decision is the **single LLM judgment in the routing path**. It gets an eval golden set (§3.6): clearly-design turns, clearly-strategy turns, and the ambiguous middle ("will this ad resonate with CFOs?"), regression-gated so a model swap cannot silently degrade exit behavior.

### 2.3 The delegation context bundle

Assembled by the platform side when the leg starts; passed by value/reference to the design subagent:

| Item | Content |
|---|---|
| Content-schema instance | The calibrated content for this account/campaign (the content plane's schema instance) — what the design should say |
| Brand kit reference | **Version-pinned** brand kit (tokens, fonts, logos, voice) |
| Claim references | Research claims the design may cite, by reference (ids), never as pasted blobs |
| Tenancy | `workspace_id` — carried on every row and event the leg produces |
| Target document | Document reference (existing doc to edit, or instruction to create) |
| Turn contract | Propose→Accept/Reject semantics; one-clarification-round policy |

### 2.4 Canvas context per turn

The existing MVP behavior is preserved exactly, relocated onto the platform's turn API: when the user selects an element/node in the canvas, the frontend attaches the selection to their next message as domain-object references (`focus_refs` on the turn request — the field already exists in the platform's turn contracts). The design subsystem's current `target_node_ids` + `active_page_id` + document reference map onto it nearly verbatim, alongside `previous_turn_outcome` for the clarification-round policy. The agent therefore always knows *what* the user is pointing at, per message, with no extra round trip.

### 2.5 What the platform substrate guarantees underneath the graph

The graph is the routing mechanism; the substrate contract is unchanged and non-negotiable:

- **One thread, owned by the substrate.** Every turn — platform's and design's — lands on the same `thread_id` as `agent_turn` rows with per-turn agent role attribution; message bodies are content-addressed artifacts (tenant-scoped, retention-classed, tombstone-able), never inline text. The design leg is scoped under its parent via `parent_execution_id`.
- **Per-agent context by filtered assembly.** The design deepagent's context = leg-scoped history + its bundle. The platform deepagent's context = its own turns + leg summaries. Neither ever ingests the other's full transcript.
- **One event stream.** All leg activity — agent progress, proposals ready, operations applied, previews available, accept/reject resolutions — is emitted as `design.*` topics on the platform's durable `run_event` stream (token-authenticated SSE, seq-idempotent replay). The frontend renders one stream for the whole session.
- **Durable interruption.** The interrupted graph state persists in the **Postgres checkpointer** and is resumable by **any** fleet worker. An open design session paused at the HITL node survives process restarts and deploys. (The design subsystem's current daemon-thread execution — where a restart kills every running turn — is the named anti-pattern this replaces.)
- **The passive speaker indicator.** The UI displays who is currently answering (platform vs design agent), derived from the same graph state. It is **display-only** — it is never a control, and no routing behavior depends on it.

---

## 3. Plan of action

### Part I — Repo unification with history preservation

**Goal:** one monorepo; the design subsystem lives under `subsystems/clue-design/`; its full commit history — every author, date, message, blame line — is preserved and independently queryable.

#### Step 0 — Audit & freeze (≤1 day)

All history work targets the **real repos** — the latest main copy of the design repo is at `/Users/aryankeshri/conductor/repos/clue-design`, and the platform repo is at `/Users/aryankeshri/conductor/repos/research-and-data` — never the Conductor worktree checkouts (their `.git` files are pointers into these real repos).

1. Blob-size histogram + `git count-objects -vH` on `clue-design` history — this feeds the strip list. **Final ruling, as executed 2026-08-07** (earlier keep/strip rulings evolved during execution; this is the settled shape):
   - **Committed (in history, on every clone):** `.context/` **markdown** — the implementation-strategy notes; the `docs/` images (`agent-mode.png`, `editor-mode.png` — stripped by an over-broad glob during cleanup, restored by an ordinary commit); test fixtures (e.g. the ingestion brand-kit PDF).
   - **Stripped from history, kept local-only (present on disk, gitignored, never pushed):** `apps/api/asset-store/`, `apps/agent_runtime/.lumen-runs-A/` + `.lumen-runs-B/` run traces, `.context/a0-probe/`, `.context/attachments/`, all `.context/**/*.png`, `.playwright-mcp/`, `apps/editor/public/vendor/`, and the root screenshot PNGs. These are dev-generated/regenerable artifacts; the working copies live on in the worktree via `cp` from the old havana checkout, invisible to git via the `subsystems/clue-design/.gitignore` block committed with the cleanup.
   - (The nested `google-fonts` git clone inside `.context/` is an embedded repo — never tracked, never in history, no action needed.)
2. Secret-scan both histories (gitleaks/trufflehog); strip + rotate on any hit before rewritten history goes anywhere.
3. Freeze the design repo: land or park all its in-flight branches. **The platform repo needs no freeze** — its history is never rewritten (see Step 1), so in-flight platform branches (e.g., C8) survive untouched and continue in parallel.
4. Inventory Conductor workspaces on the design repo — all must be recreated post-rewrite.

**Gate:** strip list final, secret scan clean, design-side freeze agreed, dry run of Step 1 green on throwaway clones.

#### Step 1 — The merge (1 day)

Work on fresh, disposable clones. The platform repo's history is **only merged into, never rewritten** — platform commit hashes do not change.

```bash
# Disposable working copies (--no-local forces a clean, self-contained clone;
# filter-repo requires a fresh clone and the real repos host live worktrees)
git clone --no-local /Users/aryankeshri/conductor/repos/clue-design        havana-rw
git clone --no-local /Users/aryankeshri/conductor/repos/research-and-data  platform-rw

# Rewrite the design repo's history:
cd havana-rw
# (a) strip exhaust from all history — removes these blobs from every commit ever
#     (.context/ and apps/api/asset-store/ are deliberately NOT listed —
#      retained per the 2026-08-03/04 rulings)
git filter-repo --invert-paths \
    --path .playwright-mcp/ \
    --path apps/editor/public/vendor/ \
    --path-glob 'aq-e2e-*.png' --path-glob 'hy-e2e-*.png' \
    --path-glob 'step*.png'    --path wasm-banner-stop.png
    # plus everything the Step-0 histogram flagged
# (b) relocate the entire history under subsystems/clue-design/ — as if it had always lived there
git filter-repo --to-subdirectory-filter subsystems/clue-design/

# Graft onto the platform repo, on a feature branch:
cd ../platform-rw
git checkout -b platform/monorepo-merge
git remote add havana ../havana-rw && git fetch havana
git tag design-import havana/main          # permanent anchor: "design history up to import"
git merge --allow-unrelated-histories havana/main \
    -m "merge: absorb clue-design as subsystems/clue-design/ (history preserved)"
git remote remove havana
```

The subdirectory filter dissolves every root-level collision (`docs/`, `scripts/`, `CLAUDE.md`/`AGENTS.md`, README case clash) in one stroke, since nothing from the design repo remains at the root.

*As executed (2026-08-04 → 2026-08-07):* the actual run deviated from the single-pass script above, with an identical end state — recorded so nobody re-derives it:
- The relocation ran in two steps (rewrite to `design/`, then `git filter-repo --force --path-rename design/:subsystems/clue-design/` after the placement decision moved). `--force` was acceptable only on the disposable, already-rewritten clone.
- The heavy-artifact strip ran **after** the merge branch was first pushed, as a branch-scoped rewrite (`git filter-repo --force --refs refs/heads/<branch> --invert-paths …` on a fresh clone) followed by a force-push of that branch only. Platform-side commits came through hash-identical; `main` was never rewritten.
- The canonical branch is **`platform/monorepo-merge-v1`** (a Conductor-created fork of the merge branch; it initially forked from the *pre-cleanup* tip and carried the heavy blobs, so the same `--refs` strip was re-run against it directly). Lesson recorded: a branch forked before a history rewrite keeps the dirty ancestry — re-strip the fork, don't trust the fork point.
- filter-repo glob footgun: in `--path-glob`, `*` matches across `/`, so `subsystems/clue-design/*.png` (meant for root screenshots) also stripped `docs/*.png`; the two docs images were restored by a normal commit afterwards.
- Verification standard: `git rev-list --objects <branch> | git cat-file --batch-check=… | awk '$1=="blob" && $3>1000000'` must list only the deliberate keepers (docs images + test-fixture PDF). Pack size is a hint; the blob check is the truth.

**History tracking afterwards** (the answer to "can we still track design history separately"): yes, natively —
- `git log subsystems/clue-design/…` — full design-subsystem history for any path, original authors/dates/messages intact;
- `git blame` on any design file walks to the original writing commit; `--follow` traces pre-merge renames;
- `git log design-import` (the tag = the merge commit's second parent) walks the design-only ancestry, nothing else;
- the archived read-only `clue-design` repo retains the original (pre-rewrite) hashes for cross-reference.

**Merge-day commit series** (same branch, one concern per commit): root doc reconciliation (root `CLAUDE.md` points into `subsystems/clue-design/`); root-anchor audit for the few true root-relative paths in design code (env loading, setup scripts, CI paths — the internal `parents[N]`/`../..` climbs survive because the tree moved as a unit); delete the frozen `lumen_pipeline_archive/` dead code; **add the uv-workspace guard** — because the tree now sits *inside* the `subsystems/*` uv glob, `[tool.uv.workspace] exclude = ["subsystems/clue-design"]` must land in the root `pyproject.toml` in this same series, before any `uv sync`, so uv does not treat the three-language root as a Python member; union the `.gitignore`s (scoped under `subsystems/clue-design/`, plus the stripped paths so they can't return); import the design CI jobs with `paths:` filters so platform-only commits stay fast.

**Cut-over:** branch builds green on both toolchains → swap in as origin → archive `clue-design` read-only same day → recreate design-side Conductor workspaces.

#### Step 2 — Week-one hygiene

1. **Deduplicate the shared libraries.** `subsystems/clue-design/py_lumen_obs` and `subsystems/clue-design/py_lumen_config` are pre-fork ancestors of the platform's `clue-obs`/`clue-config`; fold any post-fork improvements into the clue libs, migrate the design imports, delete the duplicates.
2. **Real packaging.** Proper `pyproject.toml`s for `subsystems/clue-design/apps/api` and `subsystems/clue-design/apps/agent_runtime`; add them to the uv workspace **as explicit members** (the merge-day `exclude = ["subsystems/clue-design"]` guard keeps the non-Python root out of the `subsystems/*` glob; the Python apps re-enter individually, by exact path, once they have pyprojects); kill the `sys.path` hacks. The package-layout and structure-guard tests gain a carve-out for `subsystems/clue-design` as the one non-Python-subsystem resident of `subsystems/`.
3. **One version story.** Python 3.12 everywhere; one `deepagents` pin (the platform's); one `langchain-*` resolution in the lockfile.
4. **Gradual strict gates.** Design Python enters ruff-format immediately and mypy-strict via per-module lenient overrides with a tracked burn-down. `make check` stays green at every commit.
5. **Import contracts extended.** Register the new packages in import-linter; add the design seam contracts: design never imports research/memory/content internals (and vice versa); design Python touches the Rust engine only via the `lumen-api-helper` subprocess seam; nothing outside `subsystems/clue-design/` imports design internals except the composition root.
6. **Path-filtered CI.** Design jobs (cargo test, wasm build + engine-handshake verify, editor vitest/tsc, design-API pytest, design-agent pytest — the last currently ungated anywhere) run only on `subsystems/clue-design/**` changes; `subsystems/clue-design/crates/lumen-core/**` is the one global design-side gate (it changes the engine stamp, so everything design-side rebuilds); the `lumen-api-helper` binary and wasm artifact are cached job artifacts, not per-job rebuilds; the platform's existing pipeline is untouched and unslowed.

**Gate:** one obs, one config, one Python, one deepagents pin; all design packages under contracts; all CI lanes green including design-agent tests.

### Part II — Substrate adoption (design backend onto platform substrates)

Order matters: tenancy first, then persistence, then execution.

1. **Tenancy + Postgres.** The design subsystem's SQLite tables (documents, operation log, snapshots, template revisions, binding sets, instances/batches, brand kits, web publishes, custom components, asset metadata) are redesigned as platform Alembic migrations — hash ids, reversible, single head — with `workspace_id NOT NULL` on every row from birth, and `design_`-prefixed table names (same schema as the platform tables; the design repo's generic names — `documents`, `run_events` — would otherwise collide). Dev-only SQLite data is not migrated; schema + code port, dev data resets. Foreign keys to the workspace, account-entity, and brand spine are the point: tenancy and referential integrity are *enforced*, not promised.
2. **Concept joins.** Design brand kits ↔ the platform brand spine. Design "accounts" (the ABM **target companies** whose data populates personalized instances — not client tenants) become projections over the platform's workspace-scoped account entities rather than a parallel store. Design assets move to the platform's content-addressed storage (fs/S3) instead of an API-local directory.
3. **Execution onto the fleet.** Design agent runs stop living on daemon threads inside the API process. They run under the platform's fleet (leases, supervised heartbeats, takeover semantics) with LangGraph state in the Postgres checkpointer — the prerequisite for §2.5's durable interruption.
4. **Design writes through the toolbelt.** The design API's write operations and the agent's substrate tools register as typed, precondition-checked, idempotency-keyed tools at the composition root, behind the platform's single write path. The Rust helper binary remains the engine seam; the toolbelt becomes the governance seam.
5. **Design events onto the platform stream.** The design subsystem's SQLite-polling SSE is retired. Leg activity emits `design.*` topics on the durable `run_event` stream. One transport, one auth model (single-use stream tokens), one replay semantics. Where the stream's subject key assumes a project run, widen the subject (`subject_kind` + `subject_id`) so a design leg is a first-class stream subject.

**Gate:** every design row tenant-scoped in Postgres; design agent runs survive a process restart; all design writes tool-governed; SQLite deleted; one SSE stream serves design events.

### Part III — Agent integration (the §2 architecture, built)

1. **Register the design deepagent in the platform agent catalog.** New role + versioned profile/prompt/skills; the orchestrator/author/reviewer trio and the virtual-workspace pattern port onto the platform agent runtime (same `deepagents` framework on both sides — this is a port, not a rewrite). Model access moves onto the platform's LLM gateway (verify multimodal support and per-role usage attribution survive the move — both are hard requirements of the design agent).
2. **Build the leg graph.** The three-node LangGraph of §2: design deepagent node → HITL `interrupt` node → END; compiled with the Postgres checkpointer; graph `thread_id` = leg id.
3. **Attach as a subagent + wire delegation.** The platform deepagent gains the design subagent; delegation assembles the §2.3 context bundle; the engine records the leg (parented to the platform execution) and flips the thread's active-speaker state that the passive indicator reads.
4. **Implement message routing on graph state.** The turn-ingestion path applies the one rule: innermost interrupted graph gets the message (resuming it at the HITL node); otherwise the platform deepagent gets it. No other routing input exists.
5. **Implement `finish_design_leg`.** Engine-validated exit tool per §2.2, including out-of-scope message re-delivery and resume-after-mis-exit. Journal every exit decision.
6. **Evals.** Golden set for the out-of-scope exit judgment (§2.2), wired into the regression harness so model swaps are gated; plus a resumability integration test: interrupt a leg, kill the worker, resume from another worker, assert canvas/round state intact.
7. **History assembly.** Filtered per-agent context assembly per §2.5 (leg-scoped for design; own-turns + summaries for platform), composed with the stage0/context-assembly improvements landing on the C8 line — Part III starts after C8 merges, and its delegation-bundle assembly builds on C8's mechanism rather than forking it.

**Gate:** a full session runs end to end in one thread — strategy turns with the platform agent → delegation → multi-round direct design iteration with canvas selections → lock-in exit with summary return → platform agent resumes; separately, an out-of-scope exit re-delivers the pending question and a re-delegation resumes the same leg. All of it survives a mid-leg worker restart.

### Part IV — Surface integration (the editor inside the platform frontend)

1. **Extract the editor core as a package.** The design editor's React-free engine layer (wasm bindings, engine handshake, document/state/command logic, API client) becomes an importable package; the three known debts are dissolved in the process (the shell god-component, the ~30-field hook dependency interface, inline env/asset-URL assumptions → injected config). The current design-repo Next app demotes to an internal dev harness consuming the same package.
2. **Mount in the platform shell.** The new platform frontend (built from the new Figma design) owns chat + project/thread structure; when a design leg opens, the editor mounts as an in-session surface — same page, same thread, same stream. Canvas selections flow into turn requests as `focus_refs` (§2.4); agent-applied operations stream back over `design.*` events and render live on the canvas.
3. **Speaker indicator.** The passive chip (§2.5), driven by leg state from the stream. Display-only.
4. **Parity gate.** The existing design-editor e2e screenshot suite is the parity checklist; the old standalone editor UX retires only when the mounted surface passes it.
5. **Public-URL routing — retire the Part-II interim scheme (O6b debt).** Ratified 2026-08-07 (PD contract `docs/specs/PD-part2-design-substrate.md` §6, O6/O6b): publish slugs are **workspace-local** (`design_web_publish` PK `(workspace_id, slug)`), so from Part-II D2 the design API's standalone public serving uses a **temporary workspace-scoped route** (`/w/{workspace_id}/p/{slug}`) in place of the old ambiguous `/p/{slug}` — dev-only traffic, no new table, deliberately disposable. **Part IV owns the real answer**: the serving layer maps a globally unambiguous public URL onto the tenant-local `(workspace_id, slug)` identity (candidates: tenant subdomain, `platform.com/w/{workspace}/{slug}` paths, or a globally-allocated public alias). When that routing ships, the interim route is **deleted**, not kept as a fallback.

**Gate:** the §1 paragraph is demo-able as one continuous session in the new shell — and the Part-II interim public route is gone.

---

## 4. Sequencing, parallelism, and dependencies

```
Part I  (repo)        ── independent; C8 and other platform branches continue in parallel
Part II (substrate)   ── after Part I; independent of C8
Part III (agent)      ── after Part II *and* after C8 lands (context assembly dependency)
Part IV (surface)     ── package extraction can start during Part II; the mounted
                         surface needs Part III's leg + stream to be end-to-end
```

- The platform repo's history is never rewritten, so no platform branch is ever invalidated by this plan.
- The design repo freezes only for the Step-1 rewrite window (about a day).
- The engine (Rust crates, helper seam, handshake, wasm pipeline) is untouched by all four parts.

## 5. Risks and their answers

| Risk | Answer |
|---|---|
| History rewrite damages the live repos | All rewriting on disposable fresh clones; real repos untouched until cut-over; design repo archived read-only, retaining original hashes |
| Design-history archaeology lost | Subdirectory filter preserves it natively (`log`/`blame` on `subsystems/clue-design/…`); `design-import` tag anchors the design-only ancestry |
| Secrets or bloat ride into the monorepo | Step-0 secret scan + blob histogram feed the filter-repo strip list |
| Wrong out-of-scope exit mid-design | Structured exit + journaling; checkpointed leg resumes on re-delegation — a mis-exit loses nothing; golden-set regression gate on the exit judgment |
| Open design session dies on restart/deploy | Postgres-checkpointed interrupts, fleet-resumable; explicit kill-and-resume integration test |
| User confused about who is answering | Passive speaker indicator (display-only); out-of-scope exits answer misdirected questions immediately via message re-delivery |
| Design tables collide or leak across tenants | `design_` prefix; `workspace_id NOT NULL` from birth; FKs to the workspace/account/brand spine enforce scoping |
| CI slows for platform-only work | Path-filtered design jobs; cached helper/wasm artifacts; platform pipeline untouched |
| Context-assembly rework (C8) conflicts | Part III explicitly sequenced after C8; delegation bundle builds on C8's mechanism |

## 6. Definition of done

The plan is complete when a user can, in one uninterrupted thread in the new platform shell: run Stage-0 and research with the platform deepagent → ask for a design for a researched target account → iterate directly with the design deepagent across multiple rounds, including canvas-selection-scoped edits → lock the design → see the platform deepagent resume with the design summary in hand → and, in a separate session, verify that an out-of-scope question mid-design is answered by the platform deepagent without repetition, that "go back to the design" resumes the same leg, and that a worker restart mid-leg loses nothing. All design data tenant-scoped in Postgres; all design history queryable via `git log subsystems/clue-design/`; all CI lanes green.

---

*Owner: Aryan. Adopted 2026-08-03. This document supersedes the earlier merge playbook's routing sections (which described a UI-focus-based routing model, since rejected); the playbook's repo-mechanics content is restated here in full, so this document stands alone.*
