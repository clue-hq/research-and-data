# Scene skill family implementation slice

- Implemented candidate scene view under knowledge_docs/views/scene with one
  autonomous brief/copy entry point, four initial playbooks, shared native-layer,
  source-role, direction and review guidance. Legacy remains the default.
- Runtime selects the candidate view explicitly and roots candidate scene runs
  beneath configured trace_dir/scene-candidate. Real web/scene interleaving tests
  preserve website prompts, skill index and pins; API trace adapter consumes the
  returned nested tools.trace_dir successfully.
- Shared grammar's image-policy section is projected for candidate only; website
  grammar is unchanged. Candidate pins read delivered projected bytes. Shared
  mechanics are not copied into another complete grammar file.
- CreativeDirection validates handoff structure/joins; copy_blocks aliases JSON
  copy. Scoped edit intent permits no new copy. Runtime root owns catalog/source
  validation and current-scene acceptance/critique observation.
- Focused suite: 22 passed. Wider 199-test resource matrix: 198 passed and one
  legacy source-string acceptance assertion needs root-owned fixture repair.
  Earlier harness matrix had four acceptance-fixture and one provider-fixture
  failures, reported to their owners. New code has no Ruff diagnostic increase
  over HEAD; new model/tests/materializer pass Ruff; diff whitespace checked.
- No services, browser, database, paid generation, model/env-secret edits, commits
  or remote actions by this worker. Root handles all commits and live evaluation.
- Full handoff: .superpowers/sdd/design-agent-v1-skill-family-plan/task-1-report.md.
  Eight short-request cases are prepared beside it, not live evaluated. Offline
  success does not establish visual quality or evidence truth.

### Post-smoke checkpoint correction

Read-only live observation showed skipping the director render also skipped the runtime's only mid-round scene checkpoint. Root authorized a bounded correction: render.py can reuse a current clean SVG/PNG receipt while still calling the real checkpoint callback and copying into the current round; candidate director step5 explicitly calls it again. Stale, changed, debug, invalid, missing and single-format evidence falls through normal export. No active runtime/materialized content, env/model, services or DB were modified. Red test reproduced duplicate exports; focused render/checkpoint/fastloop112 pass and isolated scene-family22 pass, with Ruff/diff whitespace clean. Narrow combined test order exposed existing framework-stub backend import contamination (`ls` missing); reported to root. Full scope and commands appended to task1 report. Root owns commits and live integration.

### Harness fixture isolation correction

Root authorized fixing the earlier test-order caveat only in test_deepagent_harness.py. Reproduced fast_loop→scene_skill_family106passed/1failed; the fixture replaced filesystem modules during first lazy import, permanently giving AgentWorkspaceBackend a fake base. Changed three stubbing sites to patch agent construction only, retaining real filesystem/state classes. Same order plus harness tests160passed; diff whitespace clean. Production unchanged, no commits/restarts.
