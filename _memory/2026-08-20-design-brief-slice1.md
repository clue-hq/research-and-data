# 2026-08-20 — brand design-brief plan, slice 1: `design-guidance` wired must-read (tier-1 wiring)

Plan: `docs/superpowers/plans/2026-08-20-brand-design-brief-and-craft-skill.md` §5 slice 1.
Branch `integration/frontend-design-part-iv-v2`, worked directly. Division of labor
(founder): the controller AUTHORS the skill text (`fb587841`); this session did the
WIRING + TESTS and never edited `knowledge_docs/skills/design-guidance/SKILL.md`.

## What landed

1. **Knowledge tree — nothing to register.** Skill discovery is IMPLICIT, by directory:
   `lumen_agent/materialize.py` copies the whole `knowledge_docs/skills/` tree into the
   isolated workspace (`/.deepagent/skills/<name>/` — the `SkillsMiddleware` source — plus
   the full `knowledge_docs/` copy), content-stamp guarded. There is no manifest and no
   enumeration: `knowledge.py`'s `PRIMARY_KNOWLEDGE_PATHS` lists only `knowledge/**` docs,
   never skills (none of the other 13 are listed either). So `design-guidance` was already
   picked up the moment its directory existed — proven by a load test rather than assumed.
2. **Prompts (`lumen_agent/prompts_web.py`)** — web roles only:
   - orchestrator OPERATING SHAPE step 1 now carries `Read your skill: design-guidance —
     must-read on every web turn…` beside the existing landing-page/abm-page recipe pointer,
     before the BRAND ANCHOR instruction (short pointer; the skill is the content);
   - the author's opening line now reads TWO must-read skills — `create-website` (contract)
     and `design-guidance` (deployment grammar);
   - one disambiguation: the author's kill-test line said "see the skill's Design guidance"
     (meaning create-website's §Design guidance) — now says so explicitly, since a skill of
     that name exists;
   - the **reviewer prompt is byte-untouched** (its hooks are a SKILL.md edit), and the
     **scene prompts (`prompts.py`) are byte-untouched** (D4: web documents only in v1).
3. **`knowledge_docs/skills/review-website/SKILL.md`** — one new tight section, in the
   file's voice, between the anchor check and the personalization check: *"When a Creative
   Brief reaches you"* — (a) the brief's `constraints` are review criteria and a violation
   is a reportable **defect**, not taste (a user-forced deviation is the director's to
   reconcile); (b) the page's band sequence is checked against the brief's
   `background_rhythm`, the ratio's spirit not a section count; with no brief the existing
   Rhythm checklist item stays the bar. Nothing restructured, no existing item touched.
4. **`knowledge_docs/AGENT.md`** (materialized as the agent's `/.deepagent/AGENTS.md` — the
   founder's system-prompt/AGENTS.md layer): a §4 knowledge-map row *"Any website turn"*
   naming `skills/design-guidance` **must-read** (plus the web skills + recipes the row
   needs to be honest) and a §5 skills-index row for it. The root doc had NO website rows
   at all before this — the web skills existed in the tree but were unindexed.
5. **Tests** — `apps/agent_runtime/tests/test_design_guidance_wiring.py` (9, TDD: 4 red
   first, the registration/scene/reviewer ones green from the start, which is itself the
   proof that registration is implicit).

## Verification

- `PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/python -m pytest apps/agent_runtime/tests`
  (from `subsystems/clue-design`, root `.venv`, **without** the platform root `.env`
  sourced — recorded trap) → **587 passed, 2 skipped** (was 578+2 at the G9 wave; +9).
- No live generation (slice 4 owns the coherence walk). No server touched, nothing restarted.
- `grep` proof: `design-guidance` appears in `prompts_web.py:97` (orchestrator), `:204`
  (author), `AGENT.md:81` (knowledge map) and `:116` (skills index).

## Concerns / follow-ups for the controller and slice 4

- **The reviewer cannot see a brief yet.** `build_web_reviewer_prompt()` takes no
  `brand_card` — the reviewer subagent receives only the director's delegation brief. So
  review-website's new hooks are dormant until slice 4 threads the brief to the reviewer
  (either a reviewer-prompt brand/brief block or an orchestrator instruction to quote the
  brief's `constraints` + `background_rhythm` into the delegation). The SKILL text is worded
  to be true either way ("in the brand card or quoted in the director's brief").
- **Skill-text notes (controller's call, NOT edited here):** the pre-finalize ritual and the
  adherence ladder both address `finalize_web_run` / "your finalize summary", but
  `finalize_web_run` is an ORCHESTRATOR-ONLY tool — the author has no finalize step and
  reports to the director instead. Also `create-website §Composable primitives` is cited as
  a section; in that file it is item 3 of §Design guidance. Both cosmetic; every token/class
  the skill names (`bg-primary/10`, `text-inverse`, the `data-button` variants, the
  band-alternation rule, the two recipe paths) checks out against the runtime.
- **AGENT.md is scene-era.** Its §5 index still omits create-website / edit-website /
  review-website (only design-guidance was added, per this slice's ask). Worth a sweep when
  someone owns that doc.
