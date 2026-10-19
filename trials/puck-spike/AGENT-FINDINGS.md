# Puck spike, phase 2: findings (2026-10-08)

## The question and the answer

**The question** (founder, 2026-10-07): with pages as plain React components on Puck, how easily does
our own agent work with Puck's model, does a lean harness hold up, and do the agent's productivity
and efficiency improve?

**The answer: yes, clearly, on every measure we could test.**

- **Cost:** a full 1:1 page costs $0.57–0.99, against $4.14 for the platform website agent on the
  same Syracuse input.
- **Puck mistakes:** none at all. Every page was valid at its first validation, and there were zero
  validation errors in 296 model calls.
- **Brand:** the agent stays on brand, including a section it wrote itself.

What still falls short is judgement (scope, and a brief that overrode a skill) and the inputs it is
given (capture of JavaScript-heavy sites, research coverage, images). Those are fixable, and most
would matter whichever editor we used.

**Recommendation: go for a platform integration spec** (see the roadmap,
`docs/superpowers/specs/2026-10-08-website-agent-on-puck-roadmap.md`).

## What we built

- **The harness** (`agent/trials_puck_agent/`), built on LangChain's `create_agent` and only the
  deepagents middleware we need:
  - **file tools** with writes denied on the inputs;
  - **our tools:** `validate_page`, `render_page`, `restore_version`, `view_asset`, `web_search`,
    `fetch_page`, plus `write_section` in E5;
  - **guards:** tool calls run in the order written, a finish guard (no turn ends on an invalid page),
    a 40-call safety stop, and per-call cost records.
- **Context handling**, from the platform website agent's lessons:
  - superseded results become stubs once a session passes 60k tokens;
  - compaction starts at 300k tokens and keeps the latest 60k;
  - a fresh session per request, with code-written `site.md` and `history.md` as memory.
- **Contracts in code, judgement in the prompt** (founder ruling 2026-10-08). The validator checks
  components, slots, text that exists, links between pages, kit images and one destination. Numbers,
  named people and the brief's notes are the agent's judgement.
- **Three skills** (`account-page-copy`, `building-with-puck`, `page-review`; about 2,200 words),
  carried in the system prompt, plus `writing-a-section` for E5. Every rule change since is in
  `agent/SKILLS-CHANGELOG.md` with its failing case.
- **Fixed prompt:** about 6.7k tokens with 12 tools, against about 52k tokens and 38 tools on the
  platform website agent.

## Results

All numbers come from `agent/report_tables.py` over the run records in `agent-runs/*/run.json`.

### E1: building a page

| Run | Case | Calls | Cost | Time | Renders | Validation errors |
|---|---|---|---|---|---|---|
| a1 | Garner × Syracuse | 19 | $0.82 | 5.1 min | 2 | 0 |
| a2 | Garner × Syracuse | 16 | $0.63 | 5.1 min | 2 | 0 |
| a3 | Garner × Syracuse (build turn) | 15 | $0.62 | 6.0 min | 2 | 0 |
| b1 | Conduit × Dana.AI | 17 | $0.69 | 4.7 min | 2 | 0 |
| c1 | Conduit × Atrium (thin research) | 16 | $0.57 | 3.7 min | 2 | 0 |
| a4 | Garner × Syracuse, after the proof and render-limit changes | 20 | $0.99 | 7.1 min | 3 | 0 |

- **Consistency:** the three Syracuse builds converged on the same five sections and the same proof.
  a2 and a3 have the same headline, word for word.
- **Honesty with thin research:** c1 named Atrium and said nothing else about it, and left out a
  headcount the brief told it not to use.
- **Judgement miss, every Syracuse build:** the agent followed the brief's suggested proof
  (Nightingale, whose results came with plan changes) over the skill's own fit check.
  - a1–a3 never searched Garner's site.
  - a4, after the new "treat the brief's suggestion as a suggestion" bullet, did search and saw Metal
    Exchange, but still chose Nightingale "to keep one analog". Its page also says no plan-design
    change is required.
  - **The likelier cause is the skill's own order:** "same industry and size" ranks above "same
    situation", and the fit check is a later bullet, not a gate. A reorder is proposed.
- **The new render limit worked as meant:** a4 used all three renders to fix orphan words in the hero
  and two headings. It added about $0.20 to the build.

### E2: ten edits to a built page

| | a3: one long session | E2b: a fresh session per edit |
|---|---|---|
| Total for ten edits | $6.03 · 71 min | $2.73 · 27 min |
| Average per edit | $0.60 · 7 min | $0.27 · 2.7 min |
| Largest request | 214k tokens | 53k tokens |
| Exact or sound | 7 | 8 |
| Partial | 2 | 2 |
| Failed | 1 (edit 7) | 0 |

- **a3 failed edit 7:** asked to "shorten the four cards" on a page with none, it added a section
  instead of saying so.
- **E2b got it right:** with the prompt's new rule ("if the request names something not on the
  page, say so and ask"), it said so in all three such edits (6, 7, 8).
- **Remaining partials:**
  - edit 4 also lightened the closing band;
  - E2b's edit 9 re-pointed the offer's main button to the new /analysis page.
- **Where E2b's cost went:** about $0.76 of its $2.73 was full cache misses right after each
  context-clearing step. Hence clearing now starts only above 60k tokens.

### E3: does it understand Puck?

**Zero validation errors in 296 model calls across 28 turns:**
- no unknown components;
- no invented fields;
- no wrong slot keys;
- no replacements matching nothing;
- no attempts at non-token styling.

Changes were small `edit_file` edits; multi-page work (a new page, header nav, a link) succeeded
first time. The finish guard and the loop guard never had to step in.

### E4: against the earlier baselines (Garner × Syracuse)

| Run | Cost | Calls |
|---|---|---|
| Run 3 (platform website agent) | $4.14 | 38 |
| Trial 1 (platform agent, new skills) | $3.20 | 26 |
| Staged trial (copy stage, then build) | $1.12 | 21 |
| Puck agent, a1 / a2 / a3 | $0.82 / $0.63 / $0.62 | 19 / 16 / 15 |

### E5: the agent writes a new section

- **What happened:**
  - Asked for a three-step "how the analysis works" section, the agent first checked the catalog,
    then wrote `AnalysisSteps`.
  - It passed the brand-token check and the type check on the first attempt, and validated first
    time. 13 calls, $0.35.
  - On the render it reads as Garner's (heading font and colour, eyebrow, corners, body type,
    spacing).
- **E5b, the same request with the skill's code example removed and the theme and kit files given
  to read:**
  - it found the class names without searching, but still wrote exactly three flat steps;
  - it lost two conventions the example had carried: the brand heading colour, and "the kit's Shell
    already sets the width" (its heading came out near-black, with an extra container).
  - The E5 version was better; E5b's changes were undone.
  - **Lesson:** an example that carries conventions earns its place; one that carries test-case
    content does not.

## Against the success bar in the plan

| Bar | Result |
|---|---|
| A new page under $1 and about 10 minutes, errors fixed by the agent | **Met:** $0.57–0.99, 4–7 min, no errors to fix |
| A new page rated equal to the hand-built pages | **Founder's call** (pages live at /s/agent-a1, -a2, -b1, -c1) |
| An edit under $0.05 and about 1 minute | **Not met:** $0.27 and 2.7 min on average (fresh sessions); the small edits were $0.04–0.17 |
| At least 9 of 10 edits exactly as asked | **Not met:** 8 of 10 (fresh sessions) |
| No repeated Puck mistake after the first two runs | **Met:** no Puck mistakes at all |
| Zero non-token styling; the new section passes the token check | **Met** |

## What we learned about the harness

1. **One session per request, with files as memory.** One growing session made edits 2–3× slower
   and dearer and less accurate (a3 against E2b).
2. **Context clearing only pays in long sessions.** Grok reuses only an unchanged prompt prefix, so
   stubbing an early message makes the next call miss the whole cache. Clearing now starts at 60k
   tokens.
3. **Some cache misses are the provider's.** They happened with clearing off (a2, E5), so the
   per-call cost record is what catches them.
4. **Contracts in code, judgement in the prompt.**
   - Code checks over-reach (they block a sensible rounded figure) and under-reach (they miss a
     misleading statistic). They also hide whether the agent learned the rule.
   - Rules for judgement go in the prompt, each added only with a failing case.
5. **Tool calls in one response must run in order,** or a page can be checked before it is written
   (a test fails without this).
6. **Small, real inputs beat big instructions.**
   - A text catalog of clones was enough for the agent to pick the same layouts a person picked by eye.
   - Screenshots must keep their width: a mobile render shrunk to 132 px made the review blind.
   - Images need to be viewable (`view_asset`).
7. **Conflicting instructions decide behaviour.** The brief beat the skill on proof. The lasting fix
   is upstream: the brief should describe proof candidates, not prescribe them.

## Open issues and decisions

All open items are in `ISSUES.md`. The most important ones:
- **capture of JavaScript-heavy sites** (1, 39): a prototype is under way;
- **thin research coverage** (6);
- **image descriptions** (4, 27);
- **kit rules reaching the agent** (5): the patch is parked in `proposed/`;
- **the edit cost still above target** (26, 31–34);
- **Alt Carbon × MHI** (parked).

## Spend

Phase 2 model spend: **$13.76** across 296 calls, including run a4 (plan estimate: under $15).
