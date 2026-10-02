## Summary

The design deepagent can now find anything it needs about the seller and the target account without changing what Head-of-ABM writes in the brief. On a chat-opened design leg it gets the three governed account reads Head-of-ABM has, journaled and priced the same way, and the seller's pinned brand knowledge as read-only files in its session workspace. The editor's own agent routes, the CLI and the fixtures are byte-identical. Ten commits on top of `research-streaming` (the base already holds the session-continuity work from PR #65); 33 code files, +3,416/−45, no migration, no new env key.

## Changelog

### Authority: the design role may read the target account

- Mint the immutable catalog profile `design@v2`: `design@v1` plus three pins — `read_project_accounts@1`, `read_account_research@2`, `read_claims@1`. `v1` is untouched; the registry's active design version moves to `v2`.
- Grant `AgentRole.DESIGN` on those three tools in `C6_AGENT_TOOL_AUTHORITY`. The `read_account_research` grant is at the paged `@2` contract; `@1` stays frozen for replay and granted to nobody.
- The registry's version fence for `read_account_research` / `read_discovery_run` now reads the authority table instead of hard-coding Head-of-ABM, so a role joining a fenced tool is granted on its live version only.

### Platform: `DesignPlatformReads`, the injected capability

- New `clue_api.design_loop_bridge.PlatformLoopBridge`: the one rule for calling the platform loop from a design worker thread (`run_coroutine_threadsafe` with a bounded wait; refuses a call made on the platform loop itself, a closed loop, or a timeout). Extracted from `design_memory_runtime`, which now uses it with its error codes unchanged.
- New `clue_api.design_platform_reads`: `build_design_platform_reads_factory(invoker, storage, conn_factory)` returns, per envelope, a `DesignPlatformReads` object for LEG turns only (`None` when the envelope has no `leg` block). Its three reads invoke the governed tools through the worker's shared `ToolInvoker` under the turn's workspace, one fresh operation id per call so the idempotency journal never replays a page; every call lands in the invocation journal like Head-of-ABM's. `seller_knowledge()` loads the brand-knowledge pin of the turn that opened the leg (`opened_by_turn_id`, already in the bundle), reads the pinned documents by digest, and adds the project's confirmed product set and pinned ICP path.
- A governed read's refusal (`overview_not_written`, `account_not_found`, `account_not_researched`) reaches the design side as `refused:<codes>`, not as a generic failure; other errors are `read_failed` / `platform_loop` / `loop_unavailable` / `timeout`, never carrying tool inputs.
- Composition: `fleet_main` builds the factory when the design runtime is enabled and hands it to both the inline design-leg lane and the queued `design_job` handler; `DesignTurnHost` gains `platform_reads_factory` (the design API's own embedded worker sets none).

### Design executors and runtime config

- Both executors (`_execute_agent_turn_job`, `_execute_web_turn_job`) resolve the factory for leg turns and pass `platform_reads` into `run_agent_turn_preview` / `run_web_agent_turn`, which set it on `AgentRuntimeConfig.platform_reads`. A factory that cannot compose is logged and the turn designs from the brief as before.

### Design runtime: tools, seller files, fence, prompt

- New `lumen_agent.platform_reads`: three LangChain tools (`read_project_accounts`, `read_account_research`, `read_claims`) wrapping the injected object, each answering a JSON string; a refusal is `{"error": "refused", "reasons": [...]}`, any other error `{"error": "<code>"}`; every call is recorded as a `platform_read` trace event. `write_seller_knowledge` writes `workspace/seller/index.md` (confirmed products, pinned ICP, one line per document) and each document at `seller/<path>` once per session, stamped by the pin digest, rejecting absolute or `..` paths.
- The tools are added before `finalize_run` on the solo scene graph, the trio orchestrator (and its author sub-agent), and the web orchestrator, only when the platform injected reads; `platform_reads_attached` is recorded.
- `scaffold_workspace` and the web scaffold write the seller tree after the brand card. `AgentWorkspaceBackend` refuses writes under `workspace/seller/` (`readonly_subdirs`) in scoped and unscoped modes alike.
- The solo and orchestrator prompts' gather step now lists `seller/index.md when present`, and step 2 says the account reads are how the agent learns what research found about a named target company. The word "optional" appears nowhere new.

### Skills (landed pending founder review)

- `account-adaptation`: new "Reading the account" section — find the account by name or domain, overview first, `overview_not_written` is normal, `account_not_researched` refuses the claims read, page to `next_offset`, narrow only to listed prefixes, bind copy to claim ids through `evidence_refs`, an empty field is an honest answer.
- `scene-brief-copy`: the gather sentence names `seller/index.md` and the reads for a named target company.
- `tools`: new "Platform reads" section with the three tools, their refusal shape, and where they are present.

### Tests

- New: `tests/api/test_design_platform_reads_db.py` (7: non-leg envelope gets none; the three reads answer for the leg's project on the platform loop and are journaled; three refusal codes and one empty page; seller knowledge equals the opening turn's pinned set plus the product set; a leg without a pin gets empty knowledge; a call from the platform loop is refused) and `subsystems/clue-design/apps/agent_runtime/tests/test_platform_reads.py` (8: JSON answers, refusal rendering, trace events, seller files written once per pin and rewritten on a new pin, path containment, empty knowledge writes nothing).
- Added to existing suites: the design profile resolves at `v2` with 53 pins; the authority audit covers the three grants; the handler puts the factory on the host and the lane forwards it; leg vs direct turns hand `platform_reads` / `None` to the runtime (scene and web); a leg whose reads cannot be composed still designs; the solo graph registers the reads only when injected; the `seller/` fence holds in session, run and unscoped scopes.

### Docs and records

- Design note `docs/superpowers/specs/2026-09-19-design-agent-account-and-seller-context-design.md`; plan `docs/superpowers/plans/2026-09-19-design-agent-account-and-seller-context.md`; memory closing entry in `_memory/2026-09-18-design-session-continuity.md`; the `.context` session attachments tracked per the standing rule.

## Verification

ruff + format clean; mypy 869 files clean; import contracts 28 kept / 0 broken; database gate 183 tests with the lane stack down; runtime suites 393 tests. Owed, founder-triggered on the live stack: a 1:1 ad for an account named in words with no tag (trace shows the reads, creative direction binds a claim id), a generic creative on the same project (no account read), and a contact claim read under the use-class gate with nothing about the contact on disk.
