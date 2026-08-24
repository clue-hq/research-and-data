# 2026-08-24 — colour-craft wave (design deepagent knowledge layer)

Base HEAD: `463db62c8` on `integration/frontend-design-part-iv-v4`.
Worktree provisioning served a stale base (`5ea7a8791`, the PR-#42 merge); the
tree was clean, so it was `git reset --hard 463db62c8` before any work. Verify
this every time — the stale-base trap has now bitten twice.

Content + tests only. `harness.py`, `prompts.py`, `config.py`, and the Rust
crates were NOT touched. The >1h full design suite was NOT run.

## Why — the defective output

Acceptance run #2, `run_bcdcf3e484fd48b7805c8eb561a64854`, iteration 004.
The founder's verdict: the agent used two solid saturated kit colours with a
text colour that does not pair with them, treated picking a legal token as the
END of colour thinking, and never considered a softer shade even though the kit
ships one.

Exact resolved fills from that run's `final_scene.json` (the evidence):

| node | token authored | resolved hex | verdict |
|---|---|---|---|
| `artboard` | `surface.brand` | `#533AFD` | saturated purple ground |
| `headline` | `text.primary` | `#000000` | black on the purple — the defect |
| `body` | `text.primary` | `#000000` | black on the purple — the defect |
| `cta_btn` | `surface.accent` | `#EA2261` | saturated pink ON the saturated purple |
| `cta_label` | `text.primary` | `#000000` | black on the pink plate |
| `eyebrow` | `text.inverse` | `#FFFFFF` | the only correct on-brand text |
| `logo_chip` | `surface.card` | `#F8FAFD` | empty white plate (logo bytes missing) |

The kit (`brand_card.json`, Stripe kit v9) shipped `surface.brand.subtle` =
`#ECEFFF` and `surface.inverse` = `#101214`. Neither was used. The softer shade
was available the whole time.

Two findings worth keeping:

1. **The engine under-reports this class by design.** `LUMB0807` is the text
   contrast diagnostic (`crates/lumen-core/src/brand.rs`). `text_is_large_scale`
   returns true at `font_size >= 24.0` (or `>= 18.66` at weight >= 700), and the
   required ratio drops from 4.5 to 3.0 there. Black on `#533AFD` is 3.39:1 — so
   the 16pt body WAS flagged and the 77pt headline was flagged by nothing. The
   defect that actually sank the render was invisible to preflight. That is why
   the new self-audit test is an EYES test, same reasoning as `no-collisions`.
2. **The agent made it worse across iterations.** Iterations 001–003 authored
   `text.inverse` on the headline and body. Iteration 004's authored scene has
   `text.primary` on both. It walked away from the correct answer. Separately,
   the round-1 critique recorded that on this kit `$text.inverse` was resolving
   black for the display/body roles — a token-resolution question that is NOT
   content-layer work and is left unowned (see residuals).

## What landed

**1. New craft skill `knowledge_docs/skills/color-and-contrast/SKILL.md`** (132
lines). Sections: the on-color pairing law (with the worked black-on-purple
example and both fixes); choose the shade not just the token; saturated-on-
saturated needs a separator; roles and families (structure / atmosphere / one
accent, plus the hard reject test); contrast before harmony (the four pairs, and
why the numbers miss the headline); the override clause. No frontmatter
`required_decisions` / `selection_policy`, so it stays a craft skill and the two
roster guards that enumerate non-format skills keep passing.

**2. Composed into all five format skills.** `skills/color-and-contrast` is in
each "Composes with" list, and each skill gained one on-color bullet in its own
relevant section (Brand & assets for the pilot / story / linkedin-banner, The
CTA for banners, Press-safe color for the poster). `_SHARED_COMPOSES` in
`tests/test_format_skill_library.py` carries the pointer, so the roster guards
it. `AGENT.md` gained a §4 knowledge-map row and a §5 skills-index row.

**3. CTA plate rule in the pilot skill.** Anchored on
`knowledge/design/blocks/actions`: a fixed `s(340,76)` plate written
`al(h,x(c),y(c),pad(20,40))` with `rd($radius.button)`, holding ONE label sized
`s(fill,hug) align(center)`; the plate's `y(c)` centres the label box and the
label's `align(center)` centres the glyph; the plate takes its size from its own
geometry, never from its label; never a hug WIDTH on the label (`LUMV0902`).
Also: give the label `$type.cta` and nothing bigger. `knowledge/design/blocks/
actions` was added to the pilot's pinned list and to `PILOT.pinned` in the test.
The banners skill already carried this rule verbatim, so it was left alone.

**IMPORTANT correction to the wave brief.** The brief asked for a "plate HUGS
its label plus padding (`s(hug,hug)`)" rule. That is the OPPOSITE of the
validated block, which is a fixed-size plate with a `s(fill,hug)` label, and
`blocks/actions` states plainly that a hug WIDTH on a slotted label trips
`LUMV0902`. The run's own DSL confirms the brief's diagnosis was inverted: the
CTA was authored `s(hug,hug)` with `pad($space.card.padding)` and a label at
`style($type.headline)` (48pt, `lh 3.45`), so the HUGGING plate ballooned to
380×180 around a 166pt-tall label box. Autofix then flipped the label to
hug/hug. The shipped rule follows `blocks/actions` and names the real cause.

**4. `on-color-pairing` self-audit test** in all five checklists, category
`contrast` (a real `CritiqueCategory` member). Wording is identical across the
five: every text/ground and plate/ground pair reads cleanly; dark ink on a
saturated brand ground scores 0; full-strength brand as BOTH ground and accent
scores 0. It sits inside each skill's blocking range (the pilot's "tests 1–7"
became "1–8"; the four R6 skills' "1–6" became "1–7"), so a 0 forces
`accepted=false`. All five `audit_tests` tuples updated; counts are now 9 (pilot)
and 8 (the other four), both clearing the `>= 7` assertion.

## Anti-phantom verification

Every token cited in a FORMAT skill was checked against the non-format corpus
(the oracle `_corpus()` uses) before being written: `$surface.brand`,
`$surface.brand.subtle`, `$surface.page`, `$surface.card`, `$surface.inverse`,
`$surface.accent`, `$text.primary`, `$text.inverse`, `$radius.button`,
`$type.cta` — all present. `$text.brand` is the one role documented WITHOUT the
`$` prefix (`token-taxonomy.md:56`, `brand-and-tokens/SKILL.md:17`), so it would
read as a phantom to the token guard; it is deliberately NOT cited anywhere.
`LUMB0807`, `LUMV0902`, and the `blocks/actions` geometry were each read at
source before being quoted.

## Red-proof (mutation, reverted from /tmp copies — never `git checkout`)

Backups in `/tmp/colorcraft-backup/`, driver `/tmp/mutate.py`.

1. Drop the `on-color-pairing` block from the pilot →
   `test_every_named_self_audit_test_is_present[linkedin-square-ad]` FAILED and
   `test_the_self_audit_writes_the_real_critique_shape[linkedin-square-ad]`
   FAILED (`assert 8 == 9`).
2. Remove the composes pointer from the story skill's list only → **PASSED.**
   The guard is a substring check over the whole body, and the on-color bullet
   carries a second mention. Removing BOTH mentions →
   `test_the_skill_names_the_craft_skills_it_composes_with[story-ad-9x16]`
   FAILED. Worth knowing: that guard cannot tell "in the Composes-with list"
   from "mentioned anywhere".
3. Delete `color-and-contrast/SKILL.md` → all five
   `test_every_skill_and_knowledge_path_the_skill_cites_exists[*]` FAILED, plus
   `test_a_skill_with_no_declaration_gates_on_nothing` and
   `test_selection_policy_defaults_to_llm_selectable_when_undeclared`.
4. Swap `$surface.brand.subtle` → `$surface.brand.whisper` in the pilot →
   `test_every_token_the_skill_cites_exists_elsewhere_in_the_corpus
   [linkedin-square-ad]` FAILED with `cites phantom tokens:
   ['$surface.brand.whisper']`.

Restored from /tmp after each; tree verified back to the authored state.

## Tests

`uv sync --frozen` at repo root, then from `subsystems/clue-design/apps/
agent_runtime` with the repo-root venv:

- `../../../../.venv/bin/python -m pytest tests/test_format_skill_library.py -q`
  → 143 passed.
- `../../../../.venv/bin/python -m pytest tests -p no:randomly -q` → **900
  collected, exit 0**, 3 skips (all pre-existing). Re-run green after the
  clarity pass.

Full design suite (>1h) deliberately NOT run.

## Clarity re-read

Every line written this wave was re-read once for the founder's style ruling
(one idea per sentence, plain declarative, no symbol chains, no semicolon-
spliced multi-rule lines). Changes made on that pass: split four comma-spliced
sentences in the craft skill; replaced the semicolon in the pilot's CTA rule by
breaking it into three bullets; replaced the em-dash `— never on` splice with a
plain comma clause in all four R6 on-color bullets; split the banners "because"
clause into two sentences; reworded two awkward constructions ("nothing to be
loud with", "Note where that leaves you"); rewrote the hard-reject test, which
originally said "three or more" of exactly three roles.

## Residuals

1. **`$text.inverse` resolved to black for the display/body roles on this kit.**
   The round-1 critique recorded it and iterations 001–003 authored the correct
   token yet still rendered black. That is a token-resolution / role-colour
   precedence question in the engine or the brand resolver, NOT content-layer
   work, and it was out of this wave's scope. **Unowned.** If it is real, the new
   pairing law will be authored correctly and still render wrong — so this
   should be chased before the next acceptance run judges colour.
2. `brand-and-tokens/SKILL.md:84` labels `LUMB0807` "logo on disallowed surface".
   The engine emits `LUMB0807` for TEXT CONTRAST; the logo-background code is
   `LUMB0810` (per `brand-application.md`). One-line doc fix, deliberately not
   bundled into this wave. **Unowned.**
3. The composes guard is a whole-body substring check (finding 2 above). If the
   intent is "named in the Composes-with section", the guard needs to scope to
   that section. Low priority — recorded so it is not rediscovered.
4. The empty white logo plate in the defective run was `asset.bytes_missing` on
   every kit logo variant, not a colour decision. Untouched here.
