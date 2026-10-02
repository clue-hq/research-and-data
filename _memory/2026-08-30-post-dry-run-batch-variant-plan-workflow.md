# 2026-08-30 (evening) — Post-dry-run rebuild batch: variant derivation, plan.md, workflow

Context: after dry run 1 (`_memory/2026-08-30-dry-run-1-sessions-drift.md`) and the founder's
Ploy comparison (shared: ploy-inspiration/plan-design/SKILL.md + ploy-playbook-conversation.md
+ the component-derivation transcript), a discussion fixed a four-item order; items 1–3 are
DONE and live, each with a founder pause between. Stack cycled after each; HEAD `3473e6383`.

## Shipped (all committed, tests 102 green each time)

1. **`0f2d67786` variant derivation** — adapting a HEALTHY clone is a named intent (the Ploy
   shallow-refactor equivalent). Author prompt DERIVE-A-VARIANT law; edit-website clone ladder
   now rebind → derive-variant → repair → replace; repair-cloned-sections "Adaptation is not
   repair — same door, different contract" (copy/cardinality MAY change, visual system may
   NOT, behavior inventory binds, note = "campaign variant: …", released at mint per ruling
   A); campaign-landing-page wrong-shape bullet; repair_cloned_section docstring gains TWO
   INTENTS + fixed its stale born-UNRELEASED closing paragraph (contradicted ruling A —
   was live during dry run 1 and may have deterred the tool).
2. **`0ac9cb883` plan-design skill + plan.md discipline** — workspace/plan.md before first
   mutation on substantial builds: verbatim ANCHORS + evidence policy (brief + captured
   library + registered assets ONLY, never model knowledge of the client; named
   customers/metrics/quotes/deadlines still never invented; unverified product phrasing
   tolerated until research spine lands — founder's "slightly false info" ruling as I drew
   the line, stated for override), grammar audit from real bands, per-section specs with
   named sources + planned/built/verified statuses, Review & Finish tasks up front,
   AMENDMENTS WRITTEN BEFORE ACTED ON (anti-Sessions mechanism), finalize = plan-vs-built.
   Wired into author (THE PLAN COMES BEFORE THE PAGE) and orchestrator (brief orders the
   plan). Orchestrator band-source list grew to six with DERIVE-VARIANT (item-1 gap).
   Mechanism verified, not assumed: deepagents graph.py gives EVERY subagent
   TodoListMiddleware + FilesystemMiddleware + summarization middleware on the shared
   persisted backend — author can write/read plan.md across fresh delegations today.
3. **`3473e6383` campaign-page-workflow skill** — the Ploy-style ordered roadmap (10 steps,
   each binding skills + tools): brief → survey → argument → plan → skeleton → adapt clones
   (the props step: derive once, rebind forever) → compose gaps → copy → review-against-plan
   → finalize plan-vs-built. Loop-backs = written amendments. Author index routes conversion
   pages through it; orchestrator briefs walk the same order.

## Key architectural facts learned (verify-not-assume finds)

- deepagents subagents each get filesystem + todos + **summarization middleware by default**
  (graph.py ~640) — item 4 (context offloading/compaction) may be mostly TUNING, not building.
- The web lane has its own fast-loop flag: `LUMEN_AGENT_WEB_REVIEWER` /
  `web_fast_loop` (config.py `web_reviewer_enabled`, D-F7) — reviewer quarantined by
  tool-absence when the web fast loop is on; same rubric either way. Check which state the
  env actually runs before the next dry run (dry run 1 saw zero critique events).
- Skill materialization copies knowledge_docs/skills/ wholesale — new skills ship with no
  wiring (count now 27).

## Open queue

- **Item 4 (founder-sequenced, next):** context offloading + compaction — verify the default
  summarization middleware's config on our harness paths first; founder's "samurai
  compaction" = SummarizationMiddleware.
- **Dry run 2** (same CFO brief, cold) — the regression test for this whole batch: expect
  plan.md in the run workspace, DERIVE-VARIANT for the hero instead of a from-scratch
  Sessions hero, amendments instead of the silent clear-and-rebuild.
- Drift-era library cleanup still pending founder decision (Sessions hero frag_394b9ff7,
  speakers frag_bd6ab626, agenda frag_3fed2fb8, register CTA frag_b88bb77a — all released).
- Root-cause Items 3 (render/budget-reserve) & 4 (evidence anchoring) from the ORIGINAL
  queue: largely absorbed — anchoring now lives in plan.md anchors + workflow step 2;
  render-between-passes partially absorbed by workflow step 9; budget reserve for review
  still unaddressed mechanically.
