# Deepagent Fast Loop v1 — scene-ad speed + quality restructure

**Status: RATIFIED 2026-08-24 (founder).** Drafted 2026-08-24 from the
2026-08-24 Stuttgart run forensics and the Moda architecture study. Founder
rulings R1–R2 in §2; the §9 review questions were answered 2026-08-24 and are
recorded as R3–R6 in §2. Phase 1 (P0 fixes + instrumentation) is cleared to
start.

Baseline evidence: `fleet-worker.log` runs `run_59cbf0b7…` (inner
`run_9269a8…`, 20m42s, failed on quota at finalize) and `run_c7640eee…` (inner
`run_7d4ba182…`, 43m18s, succeeded; export left blocked). Full forensics in the
2026-08-24 session notes (`_memory/`, repo root).

---

## 1. Problem and frozen baseline

The scene deepagent produces a single LinkedIn-square ad in 20–43 minutes.
Engine work is negligible (compile ~100ms, preflight ~250ms, render ~ms); wall
clock is ~99% **sequential LLM calls**. The frozen baseline (run
`run_7d4ba182…`, 2026-08-24, grok-4.6 medium reasoning):

| Metric | Baseline | Gate (v1 acceptance) |
|---|---:|---:|
| Wall time | 43m18s | **≤ 10 min hard; 5–7 min target** |
| LLM calls | 178 | ≤ 45 |
| Time to first preview | 15.4 min | ≤ 4 min |
| Input tokens | 13.5M | ≤ 3M |
| Review rounds | 3 | ≤ 1 repair round after self-audit |
| Result usable | export blocked | export clean or warnings-only |

Where the 178 calls went (measured): ~75 calls to first preview (asset-preview
hunting on disk, LUMV0820 dead-end probing, layout overflow repair), 26 + 24
calls for two reviewer round-trips, ~24 calls dripping 14 micro-compiles
(iterations 21–34, one property edit per call), remainder round 3 + finalize.

Three structural causes, in order of cost:

1. **The author is blind and context-starved.** It cannot render its own edits
   (`render_preview` is orchestrator-only), so every visual defect costs a full
   orchestrator→reviewer→critique→author round (~25 calls). It also *discovers*
   context through tools (71 file reads / 43 greps / 22 ls in one run) that a
   composed opening payload could simply hand it.
2. **Two platform bugs feed the loop.** Broken brand-asset previews
   (`asset_missing_file`, storage-ref vs engine-cache path mismatch) force
   blind asset choices the reviewer then rejects; `LUMV0820` is raised by
   preflight but unrepairable in the DSL, so the agent probes an impossible
   fix and the "successful" run ships unexportable.
3. **Micro-edit drip.** One property change per model call, each carrying
   95–124K tokens of append-only history, at 10–25s per call.

## 2. Founder rulings recorded (2026-08-24)

- **R1 — Variants deferred.** Multi-variant sets (Moda-style: N concepts,
  different playbook each) are wanted *soon* but v1 does **not** change the
  single-artboard/single-document model. The skill format (§6) must be written
  so a variant set is N invocations of the same format skill with a set-level
  concept plan — no rework when variants land.
- **R2 — Clarifying questions are conditional.** The agent assesses the brief
  against the skill's required-decisions list; if material gaps exist it asks
  (batched, once, up front), otherwise it proceeds on defaults and records
  assumptions via `record_gap`. Neither "always ask" nor "never ask."
- **R3 — Reviewer: quarantined, not deleted (answers §9.1).** The
  `lumen-visual-reviewer` subagent is retired for ALL scene turns (not only
  skill-matched ones) but its code path stays wired and re-enableable by
  config flag. Archived, not removed — the M8D-R1 quarantine pattern.
- **R4 — Budget defaults confirmed (answers §9.2).** 45 calls / 10 min wall /
  4 inner iterations ship as the config defaults.
- **R5 — Advisory export warnings are editor-surface only (answers §9.3).**
  The end client never sees them; the editor's export menu does.
- **R6 — Follow-on skill sequencing approved (answers §9.4).** After the
  pilot holds: `story-ad-9x16`, `banner-2x1`, `a4-poster`, `linkedin-banner`.

## 3. Goals and non-goals

**Goals:** the §1 gate column, with no quality regression — measured by the
self-audit scores (§5.3) plus human acceptance on the same test briefs.

**Non-goals for v1:** variant sets (R1); web turns (`create-website` loop
untouched); model/provider swaps; context-window pruning of the append-only
history (kept cache-safe; the call-count reduction is the lever, pruning is a
later optimization); reviewer changes for web documents.

## 4. P0 prerequisites — land before any loop change

These are bugs, not architecture. No loop redesign is measurable while they
stand.

- **P0.1 Asset-preview resolution.** `tools/substrate.py` (~line 1442) appends
  durable-storage references (`ws_…/design/<digest>`) onto the engine-cache
  root, producing a doubled-workspace path; every `view("asset:…")` returns
  `asset_missing_file`. Fix: resolve through the storage seam (the durable
  blob-store), not string concatenation. **Test:** end-to-end
  `view("asset:…")` against a genuine `clue-storage` asset record (current
  tests cover only design previews and unknown-id errors).
- **P0.2 LUMV0820 must be repairable or advisory.** Give the DSL an operation
  to set an image-like slot's `image_policy` and/or delete/unbind the slot
  cleanly. Until the operation exists, preflight must not raise LUMV0820 at
  *error* severity on a slot the agent cannot touch. **Test:** author-reachable
  repair path proven in an integration test; no preflight error class without a
  documented repair operation.
- **P0.3 Export severity split.** Export/preview preflight distinguishes
  **blocking** (render-impossible) from **advisory** (policy lints). Advisory
  errors export with a visible warning. The frontend export menu surfaces
  failures visibly (today the message is screen-reader-only —
  `image-export-menu.tsx`). Finalize must not record `succeeded` while a
  *blocking* export error persists (closes the "accepted but unexportable"
  loophole).
- **P0.4 Checkpoint commits.** Each accepted round's scene persists to the
  document (version bump) instead of save-on-finalize-only. A quota 403 or
  budget exhaustion then loses one round, not the run (the 20m42s run
  discarded a fully valid scene). Also gives the frontend real progress to
  show.

## 5. Loop redesign

### 5.1 Frame payload — push context, don't fetch it

The author's opening context is composed by the harness, not discovered by the
agent: the frozen brief; the round direction; the brand card **with a resolved
type ramp for the artifact's dimensions**; a compact scene digest (node tree +
key geometry, the `inspect` summary form); the asset index with *working*
preview references (P0.1); and the format skill in force (§6). Knowledge files
the skill names are pinned into the payload, not read mid-run.

Acceptance: a clean run issues **zero** `grep`/`glob`/`ls` calls and reaches
its first compile within 3 model calls.

### 5.2 Author with eyes — the micro-loop

`render_preview` is granted to the author (today: orchestrator-only,
`harness.py` subagent tool lists). The authoring loop becomes:

```
compile (whole-scene reconcile)
→ preflight → [deterministic autofix pass, §5.4] → re-preflight
→ render → view own render
→ self-audit against the skill checklist (§6)
→ fix (one batched compile) → repeat, max N inner iterations (default 4)
```

The render/look step is **mandatory before reporting done** — geometry tells
the agent nothing about how the ad reads (cropped baked-in text, unreadable
CTA: both baseline failures were visible in one render). Renders write into
the round directory as today, preserving artifact custody.

### 5.3 Reviewer retired for scene turns; the checklist survives

The `lumen-visual-reviewer` subagent is **not dispatched** on scene
`agent_turn` runs. Instead the author's final self-audit writes
`critique.json` — the same `VisualCritique` shape — scored against the format
skill's named tests (§6). The orchestrator judges the self-audit (accept /
one repair round / finalize-with-gaps) exactly as it judged reviewer
critiques; `rounds/index.md` discipline is unchanged.

Rationale (from the 2026-08-24 analysis): the reviewer's catches were entirely
*mechanical* (cropped text, contrast, dead nodes) — covered by preflight + the
author now seeing its own render — while *taste* judgment is beyond both roles
(Moda's agent states this about its own no-reviewer loop). The product's real
taste reviewer is the human in the chat leg. Cost of the subagent round-trip:
~25 calls each, ×2–3 per run.

Kept reversible: the reviewer code path stays (web turns still use their
reviewer); a config flag can re-enable it for scene turns if self-audit scores
diverge from human acceptance on a defect class.

### 5.4 Deterministic autofix below the model

Mechanical preflight diagnostics with closed-form fixes are repaired in a code
loop (compile→preflight→patch→re-preflight) without a model call, and the
model sees only the post-autofix diagnostic set. v1 candidate classes: text
overflow via measured `s(w,hug)` widening within the parent's box; missing
slot `sample`/`worst_case` text; token-fallback substitutions preflight
already computes. Anything judgment-shaped stays with the author. Each autofix
is recorded in the round's diagnostics so the agent (and the trace) knows what
moved.

### 5.5 Tool-routing rule (kills the micro-edit drip)

Written into the author prompt and every format skill: property-level edits
(`#node prop(...)`) are for **localized fixes only** — one or two nodes,
no layout implications. Any change touching layout or ≥3 nodes goes through
**one whole-scene (or whole-subtree) `reconcile` carrying every planned fix in
that batch**, with existing content copied verbatim. The baseline's
iterations 21–34 (14 compiles, ~24 calls) become 2–3 compiles under this rule.

### 5.6 Budgets and graceful finalize

Hard ceilings enforced by the harness, not the prompt: per-run model-call
budget (default 45) and wall-clock budget (default 10 min), per-round inner
iteration cap (§5.2). On exhaustion: finalize the **best accepted checkpoint**
(P0.4) with gaps recorded — never discard work, never grind past the ceiling.
The 60s per-call timeout becomes a real wall-clock watchdog (the SDK
socket-silence timeout demonstrably lets 86–104s calls through; see
`docs/case-studies/deepagent-latency.md` §"watchdog").

### 5.7 Conditional clarification (implements R2)

Each format skill declares its **required decisions** (audience, tone/energy,
offer/CTA, brand-adherence level, …) with defaults. The orchestrator's
opening move checks the brief against that list: material gaps → one batched
round of 2–4 questions (existing clarification machinery, `harness.py`
opening-move gate); otherwise proceed on defaults, `record_gap` per
assumption. "Facts it can find; taste and scope the user states."

## 6. Format-skill library v1

### 6.1 What a format skill is

A per-artifact skill in `apps/agent_runtime/knowledge_docs/skills/`, sitting
**above** the capability skills (`create-design`, `repair-design`,
`brand-and-tokens` stay the how-to layer). Discipline learned from the Moda
study: ~100 lines, opinionated, decisions pre-made — **constraints, numbers,
named tests, defaults; never design-theory prose**. Required sections:

1. **Thesis** — the one paragraph that orders every other rule.
2. **Defaults & required decisions** — dimensions/surface command, brand-
   adherence dial (strict/balanced/loose), the §5.7 question list with the
   default per entry.
3. **Concept plan gate** — what the direction must state before any DSL
   (playbook, headline, single focal point, type direction).
4. **Layout variants** — 2–3 named skeletons mapped to our archetype canon
   (`knowledge/design/layout-recipes`), with real numbers for this format.
5. **Type rules** — scale floors/ceilings for this canvas against our token
   ramp, brevity budgets (headline word cap, body char cap), font-library
   guidance, generic-face ban list.
6. **Self-audit checklist** — the named, checkable tests the §5.3
   `critique.json` scores against (single-focal-point, squint-legibility,
   headline≠caption-of-image, distinctive-asset-at-real-scale, contrast
   floor, safe-margins).
7. **Override clause** — explicit user instructions beat every rule above.

Selection: the orchestrator matches the brief to a format skill by
trigger phrases (progressive-disclosure index, as today); no match falls back
to `create-design` unchanged.

### 6.2 v1 scope

One pilot skill ships with the loop change so speed and quality are measured
together: **`linkedin-square-ad`** (draft below, §8). Follow-ons once the
pilot's metrics hold: `story-ad-9x16`, `banner-2x1`, `a4-poster`,
`linkedin-banner`.

## 7. Instrumentation, rollout, acceptance

- **Metrics first.** Before any behavior change: per-run counters
  `llm_calls_total` (by role), `input_tokens_total`, `time_to_first_preview`,
  `wall_time`, `rounds`, `autofix_count`, emitted into `run.jsonl` and the
  run-view README. The §1 baseline row is re-recorded with the new counters on
  one unchanged run for calibration.
- **Flag-gated cutover.** `LUMEN_AGENT_FAST_LOOP=1` selects the §5 loop;
  default off until acceptance. P0 fixes land unflagged (they are bug fixes).
- **Acceptance protocol.** Same brief as the baseline (Insight Health "Magic
  Doc" LinkedIn ad, same brand kit) run under the flag: every §1 gate met,
  export clean, and the human (founder) accepts the visual. One additional
  brief on a second kit to catch skill overfit.
- **Kill-switch check.** One run with the reviewer re-enabled on the new loop
  to confirm the flag path still works before we rely on it as the fallback.

## 8. Appendix — pilot skill draft: `linkedin-square-ad`

> To live at `knowledge_docs/skills/linkedin-square-ad/SKILL.md`. Numbers
> reference our token ramp and 1080×1080 canvas; the checklist is the §5.3
> self-audit rubric. Kept deliberately near 100 lines.

```markdown
---
name: linkedin-square-ad
description: Author a 1080×1080 LinkedIn feed ad end-to-end — concept plan,
  layout skeleton, type scale, brevity budgets, and the self-audit checklist.
  Use whenever the brief asks for a LinkedIn ad, feed ad, square social ad, or
  paid social creative in 1:1.
---

# LinkedIn Square Ad

An ad interrupts a scroll. In the first second the viewer must register, in
order: something worth stopping for → who it's from → the one idea → what to
do. Every rule below serves that ordering; clarity earns the seconds after.

## Defaults & required decisions
- Surface: `page ad size(1080,1080,px)`. Safe margin: 64px all sides.
- Brand adherence (ask if unstated is material; default **balanced**):
  strict = kit tokens/faces/assets only · balanced = kit defaults + limited
  complementary accents · loose = brand-inspired, kit recognizable.
- Required decisions (§ask-once): audience, offer/CTA text, tone (bold ↔
  conservative). Defaults: kit's primary audience, "Request a demo", bold.
- One ad = one audience, one promise, one ask. Kill every secondary message.

## Concept plan gate (before any DSL)
Write in the direction: the playbook (product-as-hero / before-after /
typographic-manifesto / stat-proof / problem-solution / demonstration /
juxtaposition / visual-metaphor / category-reversal / if-then), the headline
(verbatim), the single focal point, the type direction. One sentence test:
"For [audience], [brand] is the [category] that [single claim]" — if the
claim needs two sentences, the strategy is broken; ask, don't design.

## Layout skeletons (pick one, name it in the direction)
1. **Split-panel** — media 49% / panel 51% (528/552 on 1080), full-bleed
   photo one side, copy stack the other. Photo must survive a hard crop.
2. **Full-bleed statement** — inverted brand surface, type IS the hero,
   no photo. Use when the kit's imagery is weak or adherence is strict.
3. **Stat block** — one number at ≥300px carries the frame; everything else
   subordinate. Only with a sourced number from the brief or kit.

## Type
- Headline: `$type.display` at ≥64px on 1080; ≤7 words; if it isn't
  intrusive it's too small. Body: ≤160 chars, `$type.body` ≥22px. CTA label
  ≤4 words.
- Faces from the kit first; a display face from the font library may carry
  the headline when the kit voice is too neutral to stop a scroll — never
  a generic default face (the library's condensed/display voices exist for
  exactly this).
- Headline and visual are ONE idea: if the headline still works pasted on a
  different image, rework the pair. Never caption the image.

## Brand & assets
- Logo or wordmark at real scale (≥48px height) on every ad; eyebrow text is
  not a substitute. Bind `account.logo`/kit assets through slots.
- **Look at every asset you place** (`view("asset:…")`) before placing it:
  reject crops with baked-in text, check the mark's shape against its frame.
- Ornament never competes with the focal point: confine patterns to a strip,
  quadrant, or radial corner; contrast them against the content.

## Self-audit checklist (score each 0–2 in critique.json)
1. Exactly one focal point (squint: one mass, one landing spot).
2. First-second ordering present (stop → who → idea → act).
3. Headline within budget, ≥64px, not a caption of the image.
4. CTA readable at thumbnail scale; contrast ≥ 4.5:1 against its surface.
5. Logo/wordmark at real scale; no asset with cropped baked-in text.
6. All four safe margins clear; no dead/zero-size nodes.
7. Brand adherence level actually followed (tokens, faces, assets).

## Override
Explicit user instructions beat every rule above. Record each override with
`record_gap`.
```

## 9. Open questions for founder review — ANSWERED 2026-08-24

All four answered by the founder 2026-08-24; recorded as rulings R3–R6 in §2.

1. §5.3 reviewer default → **R3** (quarantined for all scene turns, not
   deleted).
2. §5.6 budget defaults → **R4** (confirmed as written).
3. P0.3 advisory-warning visibility → **R5** (editor surface only).
4. Follow-on skill sequencing → **R6** (approved as listed in §6.2).
