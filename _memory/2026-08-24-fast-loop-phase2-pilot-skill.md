# 2026-08-24 — Fast Loop Phase 2: format-skill library (§6) + pilot skill (§8)

Base: `9409fda71` (`integration/frontend-design-part-iv-v4`). Worktree was
provisioned on the stale `5ea7a8791` and was reset (clean tree) before any work —
the same stale-base provisioning issue Phase 1 hit for 3/5 agents.

Scope: spec `subsystems/clue-design/docs/deepagent-fast-loop-v1-spec.md` §6
(format-skill library) + §8 (the `linkedin-square-ad` pilot), under rulings
R1 (variant-ready), R2 (conditional clarification), R6 (follow-ons sequenced
after the pilot). Parallel agent `p2-fastloop-core` owns §5 (harness/prompts/
config) — untouched here by constraint.

## Shipped

1. `subsystems/clue-design/apps/agent_runtime/knowledge_docs/skills/linkedin-square-ad/SKILL.md`
   — 130 lines (108 non-blank; siblings run 79–113 non-blank). All seven §6.1
   sections present.
2. `knowledge_docs/AGENT.md` — two rows: §4 knowledge map ("a named artifact
   FORMAT the brief matches" → read the format skill FIRST, then the craft skills;
   no match → `create-design` unchanged) and §5 skills index. Both carry the
   trigger phrases so the doc-level route matches the frontmatter-level one.
3. `lumen_agent/knowledge.py` — `required_decision_keys(text)`, the §5.7
   machine-readable interface (below). Additive, modelled on `assumes_keys`.
4. `tests/test_format_skill_library.py` — 23 tests.

NOT shipped, deliberately (R6): `story-ad-9x16`, `banner-2x1`, `a4-poster`,
`linkedin-banner`. A test asserts their absence so an early add is a decision,
not a drift.

## The §5.7 required-decisions interface (for `p2-fastloop-core`)

Two halves of one contract, so the merge reconciles cleanly:

**Machine-readable — frontmatter.** A format skill declares:

```
required_decisions: audience, offer_cta, tone, brand_adherence
```

Flat, comma-separated — deliberately the SAME shape as the existing `assumes:`
key, because `lumen_agent.knowledge.parse_frontmatter` is a `key: value` line
reader, not YAML. No parser change needed. Read it with:

```python
from lumen_agent.knowledge import required_decision_keys
required_decision_keys(skill_md_text)   # -> ["audience", "offer_cta", "tone", "brand_adherence"]
```

Every non-format skill returns `[]`, so "no declaration" is safely "nothing to
gate on" (asserted over the whole roster).

**Human/model-readable — the table.** The skill's `## Defaults & required
decisions` section carries one row per declared id, with the columns being
exactly the `ClarificationQuestion` field names:

```
| id | question | why_it_matters | options | default |
```

so the orchestrator lifts a row straight into `request_clarification`
(`allow_freeform` is always true; `options` may be empty; `default` is never
empty — the tool rejects a blank default). Tests assert the declaration and the
table cannot drift apart (every declared id has a row; every row has 5 cells, a
question ending in `?`, a non-empty why, a non-empty default) and that the header
columns are a subset of `ClarificationQuestion.model_fields`.

**Behavioral contract stated in the skill:** material gap → ONE batched
`request_clarification` round; otherwise proceed on the default and
`record_gap(area="agent_protocol", …)` per applied assumption. Derive first
(prompt / prior turns / document / brand card) per `skills/clarify-design-brief`.

If `p2-fastloop-core` prefers a different key name or a JSON sidecar, only the
frontmatter key and `required_decision_keys` need to move — the table stays.

## Strengthened vs the §8 draft (every change is a repo-verified anchor)

Kept: structure, all seven sections, every named self-audit test, the numbers
(64pt margin floor, ≥64pt headline, ≤7 words, ≤160 chars, ≥22pt body, ≤4-word
CTA, ≥300pt stat, ≥48pt logo, 4.5:1).

- **Surface command** `page ad size(...)` → **`page linkedin_square
  size(1080,1080,px)`**, the exact line all six canon skeletons open with.
- **Split-panel 528/552 (49/51) → 456/624**, copy column 496. The draft's near-even
  split contradicts `layout-recipes` ("give the image column ~40–45%"); 456/624 is
  the mechanically-validated skeleton. A 50/50 square reads as two half-ads.
- **Skeletons mapped onto the real archetype canon** — "Full-bleed statement" is
  the *vertical-poster* on an inverted surface; "Stat block" is *numeral-hero*.
  The draft named neither, so the author could not have found the skeleton.
- **The size ramp tops out at `$type.size.9xl` (128)** — so the ≥300pt stat needs a
  RAW `font_size(300)`, not a step token. The draft's "≥300px" would have sent the
  author hunting for a token that does not exist.
- **Headline form** `style($type.headline) font_size($type.size.7xl)` (80) — the
  corpus-consistent form (foundations / blocks / patterns all use it) — with
  `$type.display` kept as the alternative the draft named, and 6xl (64) as floor.
- **Body ≥22pt kept and justified**: it is deliberately one step above the general
  1080² skeletons' 19–21pt (feed downscale), so an author reading both is not
  confused. Named the real role (`$type.body` — `blocks/README` reserves it for the
  wide square hero column) and the step token if the kit lands lower.
- **Font ban list made concrete**: Anton / Bebas Neue / Archivo Black / Bricolage
  Grotesque are the real library display voices; Arial/Helvetica/Roboto/Open Sans
  verified absent from the library, so they genuinely do not resolve.
- **LUMV0820 guidance rewritten against P0.2 as merged**: image slots are now born
  with a default policy; the repair is the one-line `#slot:key
  image_policy(fit=cover, focal_x=…, focal_y=…)` modify line, never deleting the
  slot. The draft predated P0.2 and said nothing.
- **Self-audit scoring mapped onto the REAL `VisualCritique`**, which has no
  per-test numeric field. 0–2 scores go to `acceptance_notes`
  (`"<test-name>: <score> — <why>"`), sub-2s also become `issues[]` with a real
  `CritiqueCategory`, any 0 on tests 1–6 ⇒ `accepted=false`. Following the draft
  literally would have had the author invent a key that fails validation.
- **Added the §6.1 composition section** (`brand-and-tokens`, `brand-imagery`,
  `clarify-design-brief` + the four knowledge files to pin) — required by §6.1,
  absent from the draft.
- Logo floor now reads "≥48pt height, or the kit's declared minimum size if
  larger" (`logo-and-assets`: kits declare minimum size / clearspace).

## Repo facts verified (nothing cited that was not opened)

Tokens: `$surface.inverse`, `$type.display/.headline/.body/.cta`,
`$type.size.6xl`(64)/`.7xl`(80)/`.9xl`(128)/`.xl`(24), `$opacity.scrim`(0.56) —
`design-systems/token-taxonomy.md`, `lumen-dsl/text.md:245-247`, `grammar.md:180`.
Archetypes: the six in `design/layout-recipes.md:26-33`. Faces: the display/impact
table in `design/font-library.md:77-84`. DSL: `#slot:key image_policy(...)` forms
and the born-with-policy rule at `lumen-dsl/grammar.md:124-143`, diagnostics
`LUMV0820` row. Proportions: `design/blocks/patterns.md:91-131` (Full-canvas
poster, `pad(96)`, 888 column), `layout-recipes.md:137-149` (split-panel 456/624),
`:172-182` (numeral 300pt). Contrast: `design/foundations.md:94`. Tools:
`record_gap` (`tools/substrate.py:3081`, `GapArea` enum), `view("asset:<id>")`
(`tools/view.py:194,235`). Schemas: `VisualCritique` / `VisualIssue` /
`CritiqueCategory` / `ClarificationQuestion` in `lumen_agent/models/schemas.py`.

Discovery mechanism confirmed: `materialize.py` copies every skill DIRECTORY into
`<ws>/.deepagent/skills/` (no manifest); `harness.py` points SkillsMiddleware at
that parent; progressive disclosure shows **name + description only** until the
skill is opened. Hence the trigger phrases live in the description, and the
description must stay on ONE line — `parse_frontmatter` keeps no continuations,
so a wrapped description silently loses its tail. That trap has its own test.

## Tests

`tests/test_format_skill_library.py` — 23 tests over: load/materialize smoke on
the real tree; trigger phrases + the one-line-description trap; AGENT.md routing;
§6.1 composition pointers; **every `skills/…` and `knowledge/…` path resolves**;
**every `$token` is taught somewhere in the corpus**; the surface command matches
the canon; the LUMV0820 line matches the grammar; archetypes/faces are real; the
§5.7 declaration ↔ table consistency; all seven named self-audit tests; the
critique shape; render-gated (not geometry-gated) self-audit; R6 absence of the
follow-ons.

Commands (design toolchain; root uv-managed venv, NOT the design cargo/npm gates):

```
uv sync --frozen                       # from repo root
cd subsystems/clue-design/apps/agent_runtime
../../../../.venv/bin/python -m pytest tests -q
```

Results: baseline at `9409fda71` = **644 collected, exit 0, 3 skipped**. After =
**667 collected, exit 0, 3 skipped** (+23). Green under both random and
`-p no:randomly` ordering. The >1h full design suite was NOT run (per constraint);
ruff does not cover `subsystems/clue-design` (root `extend-exclude`).

**Red-case proof** (mutations applied, suite run, then reverted): a phantom
knowledge path (`knowledge/design/ad-craft`), a phantom token
(`$type.size.11xl`), and a dropped trigger phrase (`1:1 paid social`) each failed
the suite — 4 tests red. The anti-phantom guards bite.

## Residuals / follow-ups

1. **Merge surface with `p2-fastloop-core`:** `AGENT.md` (2 rows) and
   `lumen_agent/knowledge.py` (1 additive function) are the only shared files.
   `harness.py` / `prompts.py` / `config.py` untouched. If the core agent wires
   the format skill into the scene prompts, add the prompt-side assertions to
   `test_format_skill_library.py` §2 (the `test_design_guidance_wiring.py`
   pattern is the template).
2. **`required_decision_keys` has no production caller yet** — it is the proposed
   interface, tested but unconsumed until §5.7 lands. If the core agent settles on
   a different shape, this is one function and one frontmatter key to change.
3. **Skill is 130 lines vs the "~100" discipline.** The overage is entirely the
   two sections the task mandated on top of the draft: the §5.7 decision table
   (~8 lines) and the §6.1 composition block (~10). Content was compressed twice
   rather than cutting a named test or an anchor.
4. **`$type.size.xl`/`9xl` are only published in shorthand** (`xl=24 … 9xl=128`,
   `text.md:245-247`), never fully qualified — the token test resolves those
   against the ramp declaration. If the ramp doc is ever reformatted, that helper
   in the test needs updating.
5. **Not measured.** §7's acceptance protocol (Magic Doc brief under
   `LUMEN_AGENT_FAST_LOOP=1`, §1 gates, founder visual accept) needs a live stack
   and the core loop. The pilot's quality claims are unvalidated until that run —
   and R6 gates the four follow-on skills on it.
