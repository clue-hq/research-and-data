# Agent-quality track — LUMD0401 repair-loop cluster (fixed + gate-proven)

Branch `agents/editing-roundtrip-v0`, commits `a50d74a` → `d361dad`.
Baseline: the 2e M2 gate had **3 of 4 turns dirty**. This gate: **3 of 3 clean.**

## The forensics (what "LUMD0401 flakiness" actually was)

Event-stream + trace-dir analysis of the 2e gate's failed runs decomposed the
one-liner into four distinct defects — only one of them model authoring:

1. **Variants made duplicate ids the default failure** (`run_bdfe575c`): one
   block authored two variant pages that each declared generic ids
   (`artboard`, `header`) → LUMD0401 rejects the block whole → iteration 1 of
   3 gone. No context surface stated that node ids are document-global.
2. **The deterministic LUMD0401 guard misdiagnosed that case**: it assumed the
   duplicate id already existed in the scene, told the author to "edit
   `#artboard` in place" (a phantom node → LUMD0901 if followed), and pinned
   the next iteration surgical against it (`run_a0c54fab`'s final iteration
   died exactly there — a trivial 1-op patch under a wrong constraint).
3. **Good drafts were reported as failures**: `completed_with_warnings` (loop
   kept a preflight-clean best draft, ops valid) mapped to editor "failed" at
   `agent_response_from_trace` — runs `d6e08a28` and `d77d41d` both had good
   drafts discarded with no Accept offered.
4. **No non-convergence detection**: `run_d6e08a28` answered the same critique
   with the byte-identical 1-op patch three times; nothing noticed.

## The fixes (one commit each)

- `a50d74a` **A+B** — document-global id rule stated in the author hard rules,
  the seeded recipe, and create-design's self-check; `reauthor_correction`
  grew a `duplicate_in_block` branch (offending id NOT in scene → rename-and-
  re-emit correction, deliberately NOT rerouted surgical). 3-branch unit
  coverage + loop-level proof.
- `21727a8` **C** — `completed_with_warnings` now maps to a reviewable
  PROPOSAL with the unresolved critique as advisory warning diagnostics
  (mirrors edit-scoped acceptance; advisory helper unwraps the last-feedback
  envelope).
- `5c247d9` **D** — repeat-block gate (identical re-emit → skip compile/review,
  escalate standing feedback; sits after the cluster/surgical gates so their
  specific corrections win first) + repeated-halt escalation (two consecutive
  same-code halts → pin `DSL_REF_GRAMMAR_ESCALATION` into the author request).
- `d361dad` **E** — knowledge-doc backlog: AGENT.md invariant 3 (typed refs +
  document-global ids), repair-design "repurpose a default page" playbook,
  directives.md WRONG/RIGHT ref example + node-ids-only banner, and seeded
  turns pin `directives.md` via `extra_mandatory_paths`.

## Gates

- agent_runtime suite 123 passed (+5 new tests), API suite 84 passed (+1),
  editor suite 414/415 (`NEXT_PUBLIC_LUMEN_CANVASKIT=0`, known EditorCanvas
  env-split case) — all at baseline or better.
- **Browser e2e (claude-opus-4.8 + playwright-mcp, stack synced at `d361dad`,
  handshake verified):** replayed the EXACT brief that failed the 2e gate
  (standing dark-navy instruction + 2-variant pre-brief + gym poster prompt)
  plus two edit turns. Document `doc_c9c11341…`.
  - Turn 1 (brief): iteration-1 DSL used per-variant suffixed ids
    (`artboard_a/_b`, `headline_a/_b`) — **the old failure mode never fired**;
    compiled 38 ops, preflight clean, critic ACCEPTED on iteration 1 (~2 min).
    Accept committed, both variant pages dark navy + white text.
  - Turns 2–3 (edits): compiled clean iteration 1; whole-design critique
    rejected on pre-existing variant_a overflow → **edit-scoped acceptance** →
    "Edit-scoped" proposals with 2 advisory diagnostics; both Accepts clean.
  - Zero console errors across the session. Screenshots in `browser-e2e/`.
- Notably, none of the new correction/escalation paths had to fire live —
  prevention (the id rule) beat repair, which is the intended shape. The
  repair paths are pinned by unit + loop tests.

## Still open (deliberately)

- Engine-side LUMD0901 "did you mean `#page:<id>`" hint (Rust + wasm rebuild;
  Python guard covers the editor loop today).
- Deepagent photo path LUMV0100 cold-start crash (separate backlog item).
- LUMB0613/0614 font-embeddable warnings still ride every preflight summary —
  harmless (warnings, never blocked a run) but noisy; candidate cleanup is
  marking the default brand font embeddable or filtering them from repair
  summaries.
