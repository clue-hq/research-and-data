# 2026-08-24 — Craft guidance wave (content-only) in the design deepagent corpus

Base: `8334a0458` on `integration/frontend-design-part-iv-v4` (merged fast-loop
Phase 1+2). Worktree was provisioned at the WRONG base (`5ea7a8791`, the
frontend-integration merge) with a clean tree; `git reset --hard 8334a0458` was
required before any work. **Verify the base in any follow-on worktree.**

Eight content additions adapting externally-sourced design principles into our
own words, checked against this engine. No competitor is named in any shipped
file (see "Pre-existing" below for one exception that predates this wave).

## Founder style ruling applied (mid-task)

Skill/prompt content must be CLEAR AND SIMPLE for the reading agent, not
condensed. Brevity comes from FEWER, more decisive rules — never from compressing
sentences into dense fragments. One idea per sentence. A worked example beats an
abstract clause. The "~100-line discipline" is about SCOPE, not cramming.

A review pass was run over everything written here. Four blocks were rewritten
looser after first draft: the routing rule's last bullet (split one two-idea
sentence into two), the `sb` bullet in foundations (unwound a colon-clause), the
red-vs-green bullet (a rule-of-three run-on became four short sentences plus a
3-item list), and the brand-imagery focal-point bullet (a 16-line wall became a
numbered 3-step procedure).

## What landed, and where

1. **Anti-slop tells** — `knowledge/design/foundations.md`, new
   `### Three tells that mark a design as machine-made` under the existing
   "Avoid the AI clichés". Thick single-side accent bar; pill-with-a-dot above a
   heading; em-dash-heavy copy. The pill entry cross-references the existing
   Eyebrows bullet rather than duplicating it.
2. **Comparison colors** — same file, `## Color & contrast`. Never encode a
   comparison as red-vs-green; differentiate by position/order, weight/size, or
   two tonal steps of one brand hue.
3. **Vertical balance mechanics** — same file, new
   `### Spend the slack; never stretch to fill` plus an engine subsection. See
   "Engine facts verified" — this is the one item where the guidance had to be
   written from source rather than adapted.
4. **Boldness counterweight** — same file, `## Before you build`. "Correct timid
   before you correct bold."
5. **Self-audit facts-not-adjectives** — `skills/linkedin-square-ad/SKILL.md`,
   self-audit section. Score with measurements against the named test; "looks
   clean" is how a weak design passes. No named test or verified anchor removed;
   file went 131 → 136 lines.
6. **View-then-focal-point** — `skills/brand-imagery/SKILL.md` §2, plus one
   checklist line. Three-step procedure: view the asset, convert the subject
   position to `focal_x`/`focal_y`, set it on the slot (DSL) or the node (tool).
7. **Verbatim-data contract** — `lumen_agent/prompts.py`, appended to
   `TOOL_ROUTING_RULE` (flag-on prompts only). Existing nodes are the record;
   copy strings/numbers/dates/labels exactly; N items in = N out; change the
   LAYOUT not the data; exactly two exceptions (explicit user instruction, or an
   obvious typo in narrative prose — never a number, date, name, price or label).
8. **`selection_policy` frontmatter** — spec §6.1 + the §5.7 interface table;
   reader `lumen_agent/knowledge.py::selection_policy`; declared on the pilot
   skill. `llm_selectable` (default) | `deterministic`. **Document-only — no
   production consumer**, and a test asserts that stays true.

Also fixed, because item 3 depends on it: `knowledge/lumen-dsl/layout.md`'s
anchor table called `x(anchor)` "main-axis distribution / cross-axis" and
`y(anchor)` "the other axis". That is genuinely ambiguous and, read the obvious
way, wrong. Corrected to the literal screen axes with a paragraph explaining
which one distributes per direction.

## Engine facts verified (from source, not docs)

Layout — `crates/lumen-core/src/scene.rs`, `layout.rs` (taffy 0.10.1 backend):

- `LayoutAnchor` has exactly five variants: `Start`, `Center`, `End`,
  `SpaceBetween`, `Stretch` (`scene.rs:963-971`). **There is no space-around and
  no space-evenly**; `SpaceAround`/`SpaceEvenly` are never emitted anywhere.
- `x`/`y` are literal geometric axes, NOT main/cross roles. The direction switch
  at `layout.rs:538-549` maps Row → `justify_content = main_axis_alignment(align_x)`
  and Column → `justify_content = main_axis_alignment(align_y)`. So in `al(v, …)`
  the distributing anchor is `y(…)`.
- Both anchors default to `Start` (`scene.rs:993-1010`,
  `default_layout_anchor_start`), so **children top-pack and slack collects in
  one band at the far end** unless told otherwise.
- `main_axis_alignment` (`layout.rs:1630-1637`): only `SpaceBetween` distributes.
  `Stretch` silently degrades to `Start` on the main axis and additionally warns.
- A main-axis `Fill` child absorbs slack via `flex_grow` (`layout.rs:498-515`),
  split by weight (`fill(2)` = 2× `fill(1)`). **Fallback:** if the parent's main
  axis is indefinite (hug) or free space ≤ 0, fill children are pushed into
  `fill_fallback_nodes` and stay at hug size (`layout.rs:620-653`).
- **Nothing auto-stretches.** `flex_shrink` is hard-coded 0.0 (`layout.rs:484`);
  the only `flex_grow` source is an explicit main-axis `Fill`. No scale-to-fit
  pass exists on the container path.

Image policy / focal point:

- `#slot:<key> image_policy(fit=…, focal_x=…, focal_y=…)` is real and is the
  slot-modify form (`knowledge/lumen-dsl/grammar.md:124-143`; fields `fit` ∈
  cover/contain/crop, focal axes 0..1 given together).
- The node-level path is separate: `asset(action="place", node_id=…, fit=…,
  focal_x=…, focal_y=…)` (`lumen_agent/tools/substrate.py:2021-2045`). Fit/focal
  are NOT DSL leaf props on an `image` line — grammar says so explicitly.
- **Focal origin is top-left, verified from the render math**, not assumed:
  `focal_crop_geometry` (`crates/lumen-export/src/svg.rs:1715-1755`) computes
  `offset_y = focal_y * drawn_height - box_height/2` and applies it as `y:
  -offset_y`, so `focal_y=0` shows the top. Focal crop applies only under
  `Cover`/`Crop` fit.

## Claims rejected / not written

- **The competitor's auto-layout "gotcha" was not reproduced.** Any claim that a
  fixed-height container stretches or redistributes its children automatically is
  FALSE here — `flex_shrink=0`, no auto-grow, no scale-to-fit. What was written
  instead is the verified truth: children keep their natural size, the default is
  top-pack, and the slack is claimed by an anchor or by a `fill` region or not at
  all.
- **`space-around` / `space-evenly` were not cited** as distribution options.
  They do not exist in this engine; the doc says so explicitly and a test pins the
  enum.
- **`LUMV0710` was not cited by code.** The warning is real in the engine
  (`layout.rs:1689-1702`) but `knowledge/lumen-dsl/diagnostics.md` teaches no
  LUMV07xx code at all, so naming it would have introduced a code the corpus
  cannot cross-reference. The behavior is stated in plain words instead.
- **`$border.subtle` was considered and dropped** from the accent-bar tell — the
  token is real, but naming it there implied a prescription the rule does not
  need. "A hairline rule is still fine" carries it.

## Tests

`../../../../.venv/bin/python -m pytest tests` from
`subsystems/clue-design/apps/agent_runtime` (root uv venv; the worktree had none,
so `uv sync --frozen` from repo root was needed first).

Baseline at `8334a0458`: **751 passed, 3 skipped**.
After: **760 passed, 3 skipped** (+9), green under both `-p no:randomly` and
random ordering. The >1h full design suite was NOT run, per constraint.

New tests: 4 for `selection_policy` (declared / defaults across every other
skill / `deterministic` + bad-value degradation / spec-documents-it-as-unconsumed,
including a guard that it has no production caller); 1 for the self-audit
adjective ban; 2 pinning the foundations slack claims to the Rust source (the
`LayoutAnchor` enum and the `main_axis_alignment` arms; the axis switch and the
start default); 2 for the prompt data contract (flag-on content, flag-off absence).

**Red-case proof** (mutated, run, reverted): removing `selection_policy` from the
pilot frontmatter, softening the self-audit's "looks clean", flipping the doc's
"no space-around and no space-evenly", and generalizing "Do not round 1,247 to
1,200" each turned exactly the intended test red. All four guards bite.

One trap hit and worth recording: reverting a mutation with
`git checkout <SKILL.md>` also discarded that file's legitimate edits, since both
lived in the same file. Re-applied and re-verified. Prefer a targeted inverse
edit over `git checkout` when a file holds both a mutation and real work.

## Residuals

1. **`selection_policy` has no consumer.** By design, and pinned by a test that
   fails the moment a production caller appears — that test is the reminder to
   update the spec's "document-only" wording at the same time.
2. **`grow(n)` is inert.** The DSL parses and stores it
   (`dsl.rs:4461-4467`) but the solver never reads it — grep for `grow` in
   `layout.rs` hits only the two `flex_grow` lines. Possibly a future hook,
   possibly a latent bug. Not touched here, and deliberately not mentioned in the
   guidance (teaching a no-op property would be worse than silence). **Unowned.**
3. **Pre-existing competitor mention in shipped content.** `foundations.md` and
   `skills/create-design/SKILL.md` both say "the moda rec-2 case" as an internal
   failure label. It predates this wave (the rec-2 reference-image failure is
   named throughout `docs/deepagent-architecture.md`) and was left alone as out of
   scope. If the no-competitor-names rule is meant to apply retroactively to the
   corpus, these two lines are the sweep.
4. **`foundations.md` has no content-assertion suite** of its own. The two new
   engine pins are the only tests over it; the taste guidance (items 1, 2, 4) is
   unpinned prose, like the rest of the file.
5. **Not measured.** These are craft claims. Whether the anti-slop tells and the
   verbatim contract actually change output needs the §7 acceptance run on a live
   stack, same gate as the pilot skill's own quality claims.
