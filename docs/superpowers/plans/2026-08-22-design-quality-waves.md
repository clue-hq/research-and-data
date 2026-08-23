# Design Quality Waves 1–4 — Ratified Master Plan (perception → safety → tokens → proof)

> **STATUS 2026-08-22 — RATIFIED by founder (this session), slice-by-slice dispatch on
> founder order.** Charter: the founder's quality directive after the 2026-08-20/22
> imagery waves — improve the website deepagent's artifact quality along four axes:
> (1) the agent must be able to SEE the assets it is told to use, (2) one mistake must
> stop destroying whole authored pages (granularity + severity), (3) measured brand
> geometry becomes engine law (the separately ratified geometry-token plan), (4) the
> text-to-image path is proven end-to-end and quality becomes a measured scoreboard,
> not an acceptance-walk vibe. Evidence base: the four code-inspection reports of
> 2026-08-22 (deepagent anatomy, engine atomicity, token system, imagery seam) and
> `_memory/2026-08-20-imagery-defect-register.md`.
>
> **Founder carve-outs, binding across every wave:**
> 1. **No new human-facing diagnostics.** Nothing this plan ships may surface new
>    warnings/errors in the editor or brand-context UI. All new findings are
>    agent-facing only (tool results, trace, run summary).
> 2. **No new hard blockers.** No slice introduces a new Error-severity diagnostic.
>    The geometry plan's H2 phase 3 (strict hard lint) is OUT of scope entirely, not
>    merely deferred behind a flag ruling.
>
> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development,
> slice by slice on founder order. **Process rule (founder, binding): Opus agents
> implement; the orchestrating session reviews every diff INLINE itself.** TDD
> throughout. Local commits only, never push, no AI attribution. Design tests WITHOUT
> the platform `.env`. Rust slices (W2.1, W2.3, W1.2, and the geometry plan's G1)
> carry the wasm + `lumen-api-helper` rebuild ritual (design AGENTS.md §1) and
> restarts of every process embedding the helper; check for stray 801x listeners
> before verifying. Never `git stash`. File:line anchors below verified 2026-08-22 on
> `integration/frontend-design-part-iv-v2`; re-verify before editing.

**Goal:** a chat-driven website generation that places and generates brand-true
imagery it has actually looked at, never loses authored work to a single bad token,
renders measured brand geometry mechanically, and is scored by a repeatable benchmark
instead of one-off acceptance walks.

**Spec lineage:** the strategy assessment delivered 2026-08-22 (this conversation),
built on `_memory/2026-08-20-imagery-defect-register.md` (defects C1–C22) and
`docs/superpowers/plans/2026-08-20-brand-geometry-tokens-in-the-web-grammar.md`
(Wave 3's own ratified plan — see its status header for the H1–H4 rulings).

**Sequencing:** Waves are ordered 1 → 2 → 3 → 4 by leverage, but Wave 1 (Python-only
except W1.2) and Wave 3's G2 (ingestion-side, no Rust) are independent of Wave 2 and
may be dispatched in parallel worktrees. Wave 2's Rust slices and Wave 3's G1 touch
the same crate (`lumen-web`) — do not run them in parallel worktrees; sequence them.
Wave 4 requires Waves 1–2 landed (its acceptance runs must not be confounded by
known-broken perception or page-voiding).

---

## Standing founder decisions this plan encodes

- **H1–H4 + G2 ratified 2026-08-22** with the two carve-outs above (recorded in the
  geometry plan's header). H2 phase-2 "warning" ships as **Advice-severity,
  agent-only** findings; phase 3 is out of scope.
- **Category A confirmed:** enforceable facts (radius, stroke, spacing, shadows,
  band/surface colors) get the token bridge; judgment calls (characterization,
  rhythm ratios, palette scopes, imagery posture) stay structured-brief + reviewer
  prose. No separate "agent-only" tokenization — Design.md is a projection of the
  same structured brief.
- **Severity principle (Wave 2):** severity follows *ambiguity of degradation* —
  closed-vocabulary misses degrade locally with a warning; only structural or
  asset-reference errors reject, and the rejected unit must be the smallest
  submitted unit, never the whole page. This principle only ever DOWNGRADES existing
  errors (consistent with carve-out 2).

## Founder rulings R2–R4 — RESOLVED 2026-08-22; R1 still open

- **R1 — approve kit v8** (founder-only UI action on `/brand-context`). **STILL
  OPEN.** Blocks nothing mechanically but every Wave 1/4 acceptance run is
  handicapped without it: the director already asks for v8 asset ids by name and is
  handed smaller v6 files.
- **R2 — RULED: whenever the geometry/brief stages are enabled, website ingestion
  always forces the rendered tier — no heuristic.** The founder accepts the cost
  (every ingestion slower and more expensive) for the benefit (geometry + brief
  work for every brand onboarded). Implemented as slice **W1.6** below; unblocks
  W1.4's exit gate.
- **R3 — RULED (overriding the plan's default): nearest-name substitution.** An
  unknown icon name is swapped for the closest-matching valid icon from the
  registry, with a Warning naming the swap — the page is never voided and the node
  is never dropped. Near-future direction, registered: an icons *library* offered
  via an MCP server only (out of this plan's scope). Encoded in W2.1.
- **R4 — RULED: descriptions ON by default for asset ingestion, using a very small,
  cheap image-capable model, selected via its own env var.** The env var already
  exists (`LUMEN_INGESTION_DESCRIBE_MODEL` → `lumen_ingestion_describe_model`,
  `py_lumen_config/config.py:118`, default `x-ai/grok-4.5`, stage default OFF at
  :117) — so the work is: flip the stage default ON, re-point the model default to
  a live-probe-chosen cheap vision model, document both. Encoded in W1.4.

---

## WAVE 1 — Perception: the agent can see what it chooses

*Theme: the imagery mandate says "you cannot choose what you have not looked at";
today the web lane cannot look. Python-only except W1.2 (Rust). No engine-contract
changes, no new diagnostics anywhere.*

### W1.1 — `view("asset:<id>")` on the web lane
- **Files:** `apps/agent_runtime/lumen_agent/tools/web_substrate.py` (`_view_content`
  ~4265, the target table ~4349-4358), `apps/agent_runtime/lumen_agent/tools/view.py`
  (shared attach/clamp helpers), extract the preview-path resolution currently on the
  scene tools (`tools/substrate.py:1442-1476 _asset_preview_path`) into a shared
  helper both lanes call (do NOT duplicate it).
- **Behavior:** `view("asset:<asset_id>")` resolves ids from BOTH the document's
  asset registry and `config.brand_kit_assets` (the kit manifest), returns the
  thumbnail/raster preview with label + pixel dimensions + source kind; unknown id
  → honest error string listing nearest ids (never an exception — the existing
  `view` error-string contract at web_substrate.py:4527-4537 holds).
- **Grants:** both `view` variants share `_view_content`, so the orchestrator
  (imagery decision) and author (placement) get it with no harness change; verify the
  refusal-text asymmetry (`can_render`) is untouched.
- **Tests:** kit asset viewable; document asset viewable; unknown id error string;
  SVG-without-thumbnail returns the honest "no raster preview" string until W1.2
  lands (do not fake it).

### W1.2 — SVGs become visible (Rust)
- **Files:** `crates/lumen-assets/src/ingest.rs:171-197` (vector path derives no
  thumbnail today), `crates/lumen-assets/src/thumbs.rs`. Rasterize sanitized SVGs at
  ingest into the standard thumbnail slot (existing 256/512 rules apply; pick a
  raster backend already in the dependency tree — if none, `resvg` is the default
  candidate, founder sign-off on the new dependency at dispatch).
- **Behavior:** SVG assets (including every logo) get a raster thumbnail; `view`
  and the describe stage can now see them. The style-anchor exclusion of logos and
  of non-raster records is deliberately UNCHANGED (`_clears_style_reference_floor`
  still requires the raster block; logos still never anchor).
- **Ritual:** wasm + helper rebuild, restart 8010 + fleet worker.
- **Tests:** SVG ingest produces a thumbnail; sanitizer output unchanged; existing
  raster thumbnail goldens byte-stable.

### W1.3 — the brand card tells the truth the author needs
- **Files:** `apps/agent_runtime/lumen_agent/brand_card.py` (`_image_inventory`
  210-242, `CARD_COLOR_ROLES` 24-34), `apps/agent_runtime/lumen_agent/tools/web_substrate.py`
  (`web_theme_token_names` 384-399).
- **Behavior, three fixes:**
  1. every image row gains `px: "WxH"` from the record's raster metadata (the agent
     can finally prefer a 2460px panel over a 296px thumbnail, and knows which
     images clear the 512px anchor floor);
  2. the card's color roles render **class-shaped names** exactly as the theme
     compiler emits them (`text.brand` shown as `text-brand`-usable? it is NOT —
     render the sanitized name with an explicit "kit role — the class token list
     below is authoritative" annotation), killing the `text-brand`/`brand`
     transposition trap that cost 153 live rejections;
  3. `web_theme_token_names` replicates the Rust compiler's two skip rules
     (semantic-name collision, `resolve_color` failure — `theme.rs:117-130`) so the
     prompt can never advertise a token the compiled theme did not emit.
- **Tests:** dimension field present; a kit with a colliding/unresolvable color
  yields identical token lists from Python and the helper (drift test, both layers,
  same pattern as the icon-vocabulary drift guard).

### W1.4 — descriptions on by default, cheap model, bounded (R4; fixes C9 and the bare-menu card)
- **Files:** `packages/py-lumen-config/py_lumen_config/config.py:117-118`
  (`lumen_ingestion_describe: bool = False` → `True`;
  `lumen_ingestion_describe_model` default re-pointed off `x-ai/grok-4.5`),
  `subsystems/clue-design/.../lumen_ingestion/describe.py` (top-N selection),
  `.env.example:40,48` (document `LUMEN_INGESTION_DESCRIBE` /
  `LUMEN_INGESTION_DESCRIBE_MODEL` with the probe table).
- **Behavior:** describe runs **by default** whenever an API key is configured,
  over the **top 16 images by pixel area** (16 = `brand_card.MAX_IMAGE_LIST` —
  describe exactly what the agent will be shown, nothing more) plus ALL logos
  (post-W1.2 SVGs included); the rest stay undescribed with the existing overflow
  note. A failed describe stays per-asset fail-soft (`LUMI0803` path unchanged).
  **Model (R4): a very small, cheap image-capable model**, chosen at slice time by
  a live OpenRouter probe (same evidence discipline as the image-model selection at
  `.env.example:110-139` — probe the cheap vision tier, verify caption quality on
  2-3 real kit assets, record measured per-ingestion cost in the env example);
  `LUMEN_INGESTION_DESCRIBE_MODEL` remains the per-deployment override. The brief/
  vision/assist stages keep their own models — no shared-model coupling.
- **Tests:** selection = top-N-by-area ∪ logos; cap honored; missing-key composes
  the inert describer exactly as today; the configured describe model (not the
  brief model) is the one invoked.

### W1.5 — `search_assets` finds things
- **Files:** `apps/agent_runtime/lumen_agent/tools/web_substrate.py:2874-2960`.
- **Behavior:** (1) an exact asset-id query always resolves (the 2/6 zero-result
  id lookups from the 2026-08-20 run); (2) matching includes the W1.4 descriptions
  and titles; (3) results carry `px` dimensions and a `viewable: asset:<id>` hint
  tying into W1.1; (4) empty results name the total inventory size so "nothing
  matched" is distinguishable from "nothing exists".
- **Tests:** id-hit; description-hit; the five failed queries from
  `_memory/2026-08-20-imagery-acceptance-after-asset-url-fix.md` reproduced as
  fixtures against a synthetic kit and now returning hits.

### W1.6 — website ingestion always renders (R2; the slice-4 walk's HIGH blocker)

> **[SUPERSEDED IN PART 2026-08-23 — discovered during wave execution.]** The
> force-render core of this slice ALREADY LANDED 2026-08-20 as `c9bf2859`
> ("brand-kit website ingestion always force-renders (founder ruling)"), with
> route tests pinning that a flagless request renders — the plan was drafted
> from a stale memory record. And the embedded-worker `LUMI0401
> GeometryEvidence` ImportError was root-caused live 2026-08-19/20 as a **stale
> sibling process** leasing rendered jobs from the shared queue with
> pre-geometry code (recorded at `lumen_api/main.py:369-381`) — it is the C15
> worker-version-fence class, owned by **W4.4**, not an in-repo import defect.
> W1.6's remaining deliverables: the durable-recipe `LUMEN_INGESTION_BRIEF=1`
> line in `.env.example` (done, controller edit, final review to scrutinize)
> and the live UI-path re-extract proof, which is exit-gate item (a).
- **Files:** the website-ingestion entry (`lumen_ingestion/pipeline.py` /
  `run_website_ingestion`) and/or `capture/quality_gate.py::evaluate` — force the
  rendered capture tier unconditionally whenever the geometry and/or brief stages
  are enabled; **no heuristic, no evidence-poverty escalation gate on this path**.
  The frontend `ReExtractRequest` shape (`{url, brand_kit_id}`) stays unchanged —
  the server-side force makes a `force_render` field unnecessary.
- **Prerequisite folded in (slice-4 walk blocker 3):** a `force_render` ingestion
  reproducibly FAILS in the API's **embedded** fleet worker
  (`LUMI0401 ImportError: cannot import name 'GeometryEvidence' from
  'lumen_ingestion.evidence'` — succeeds in a plain process and under
  `asyncio.to_thread`; specific to the embedded worker's runtime). With rendering
  now forced, this failure becomes load-bearing on the UI path — this slice must
  root-cause and fix it (or route UI re-extraction to the detached fleet worker),
  otherwise the UI's Re-extract flips from "publishes a geometry-less kit" to
  "fails terminally". Also: `LUMEN_INGESTION_BRIEF` remains the stage gate (default
  OFF today, slice-4 blocker 2) — this slice documents it in the durable launch
  recipe so a rendered re-extraction cannot silently publish briefless.
- **Tests:** website ingestion with geometry/brief stages on always takes the
  rendered tier (the stripe.com rich-static fixture that today short-circuits in
  10s now renders); stages off → today's behavior byte-identical; a UI-path
  re-extract job completes with geometry tokens + a brief on the fixture.

**Wave 1 exit gate (live):** (a) a UI-initiated Re-extract of stripe.com publishes
a draft kit carrying measured geometry AND a `BrandBrief@1` (the thing today's path
cannot do — this is R2's acceptance); (b) one fresh Stripe generation in which the
director's imagery decision cites at least one asset it viewed via
`view("asset:…")` (trace-proven), `search_assets` returns non-zero results for the
run's queries, and the card shows dimensions; (c) no new UI surface changed.
Honest-negative reporting as always.

---

## WAVE 2 — Stop destroying work: severity policy + edit granularity

*Theme: rejection cost follows unit size; severity follows ambiguity of degradation.
Engine-contract changes live here, all in the DOWNGRADE direction (carve-out 2:
nothing new may hard-error; carve-out 1: no new UI diagnostics).*

### W2.1 — the severity policy, written and applied (Rust; C1/C2 family)
- **Files:** `crates/lumen-web/src/ingest.rs` (header invariant 7-9, `LUMW0114` at
  :979, the severity call sites), `crates/lumen-web/src/classes.rs` (header
  rationale), the drift-guarded copies in `prompts_web.py:22-27` and
  `skills/create-website/SKILL.md` diagnostic tables.
- **Behavior:**
  1. Write the severity principle into the `ingest.rs` header as the binding rule
     for every future diagnostic.
  2. **LUMW0114 unknown icon → Warning with nearest-name substitution (R3, founder
     ruling):** the engine swaps the unknown name for the closest-matching valid
     icon from the registry (`lumen_core::icons`) and keeps the node; the Warning
     names both sides of the swap (`unknown icon 'globe' → substituted 'globe-2'`)
     so the author can correct it in a later pass if the guess is wrong. Matching
     is deterministic: normalized edit distance over the registry (case/hyphen
     folded), ties broken lexicographically; if no candidate clears a sane
     similarity threshold, fall back to dropping the icon node with the same
     Warning shape (still never voiding the page). The page is never rejected for
     an icon name again — this alone would have prevented all three recorded page
     losses. Registered future direction (founder): an icons **library** offered
     via an MCP server only — out of this plan's scope; the substitution is the
     bridge until then.
  3. **LUMW0212 stays an Error** (color is the axis that never loosens —
     `classes.rs:8-10`), but its blast radius shrinks via W2.3's smaller units, and
     its trigger causes shrink via W1.3. No other severity changes without a
     per-code founder list — W2.1's deliverable includes a one-page audit of the
     full LUMW01xx/02xx table against the principle, with recommendations, for the
     next ruling round.
  4. Update the two agent-facing contract surfaces that teach the old behavior
     (author prompt LUMW0114 paragraph; create-website skill table).
- **Ritual:** wasm + helper rebuild + restarts. **Tests:** red-proof on the exact
  2026-08-20 fixture (a valid header containing the logo + one `data-icon="globe"`
  elsewhere → page now stores, logo survives, the icon is substituted with a valid
  registry name, one warning naming the swap); the no-plausible-match fallback
  (node dropped, page stored); substitution determinism (same input → same icon);
  atomicity tests for remaining error codes unchanged; icon-vocabulary drift guard
  still green.

### W2.2 — `view("doc")` returns the tree the skills promise
- **Files:** `apps/agent_runtime/lumen_agent/tools/web_substrate.py`
  (`_doc_summary_text` 1139-1154).
- **Behavior:** full tree per section — node id, kind, class string (truncated),
  text snippet (first ~60 chars), `data-asset` refs — indented, sections
  collapsible by a `view("doc:<section_id>")` variant for large pages. This makes
  `web_ops` (the existing per-node rung) actually targetable and closes the
  50-rejections-from-guessed-ids family. Output is a tool result only (carve-out 1
  untouched).
- **Tests:** tree contains interior ids; snapshot on a fixture doc; `doc:<id>` scope.

### W2.3 — the edit floor drops below the section (Rust + Python)
- **Files:** `crates/lumen-api-helper/src/main.rs:417-425, 2432-2470`
  (`WebIngestFragment` gains an `expected_parent_kind`/context parameter),
  `crates/lumen-web/src/ingest.rs` (`finish_node` :1373-1388 — a fragment parse
  whose context says "container" accepts container/text/button/image/icon roots
  instead of erroring LUMW0102), `apps/api/lumen_api/core.py:491-508` (wire client),
  `apps/agent_runtime/lumen_agent/tools/web_substrate.py` (`_submit_subtree`
  1358-1555: resolution via `_enclosing_section` 1672-1697 becomes
  nearest-stable-ancestor — the closest ancestor with an explicit authored id,
  falling back to the enclosing section; splice batch parented on the ACTUAL parent,
  not the root).
- **Behavior:** `author_web_subtree(node_id, html)` re-authors the named node's
  nearest stable container instead of its whole top-level section. Submission stays
  atomic per unit (the five invariants hold: ops-ledger, CAS, undo inverses,
  byte-identity, contract text — only the unit shrinks). Initial page authoring is
  untouched (stays one batch; the latency model demands it).
- **Ritual:** rebuild + restarts. **Tests:** nested edit leaves sibling subtrees
  byte-identical (extend the existing `test_web_substrate.py:318` family);
  id-collision/dedupe under the new parent; replay-verifier equality on a
  sub-section splice (API-side test in `test_web_operations.py` style); a rejected
  sub-section submission changes nothing.

### W2.4 — repair ergonomics + honest affordances (Python + docs, no Rust)
- **Files:** `web_substrate.py` (`web_ops`/`set_node_props` 1774-1931 — accept a
  partial props patch merged over the current kind object; asset-id minting :3413
  switches from `len(assets)` to a monotonic counter), `prompts_web.py` +
  `skills/create-website/SKILL.md` + `skills/edit-website/SKILL.md` (patch-first
  sharpened: after ANY rejection the first move is `patch_web_page`, re-author is
  the last rung; the logo-in-a-link teaching: the legal pattern is the clickable
  container `<div data-href="/"><img data-asset=…></div>` — teach it where the logo
  is taught), `crates/lumen-web/src/ingest.rs:268,879` (the rejection hint naming
  the nonexistent `import_external_image` is corrected to name `asset(action=…)`),
  and the two FALSE scene-doc surfaces (`knowledge_docs/knowledge/lumen-dsl/diagnostics.md:5-6`,
  `knowledge_docs/skills/repair-design/SKILL.md:93-96`) corrected to the tested
  atomic truth ("a halted block applies nothing").
- **Tests:** partial-props merge; counter survives remove-then-add without
  collision; doc corrections covered by the existing seeded-continuation test's
  language (no code change needed there — the test already pins the truth).

**Wave 2 exit gate (live):** replay the 2026-08-20 failure script — a generation in
which (a) one bad icon name costs one icon, not a page; (b) a headline edit
resubmits only its container (trace shows the splice parent ≠ root); (c) zero
whole-page re-authors occur on the repair path. Measured deltas reported against the
run ledger (rejection count, author calls, wall clock).

---

## WAVE 3 — The token bridge (the ratified geometry plan, carve-outs applied)

> **[DONE 2026-08-24 — G1–G5 all landed and walk-proven** (`8086f445b..d824b1c28`);
> see the geometry plan's status header and
> `_memory/2026-08-24-wave3-geometry-tokens-complete.md` for the delivered shape,
> the live-walk evidence (adoption/DOM/parity all proven), and the registered
> follow-ups — notably: chat-driven generation is blocked on this branch until a
> rebase (sibling worktrees superseded the shared dev DB's recipe revision), kit
> v9 (latest approved) carries no BrandBrief so the brief/advice path is dark for
> chat-born docs, and Stripe's `space.card.padding` measured a chip's 7px (ingestion
> measurement-quality follow-up). Executed AHEAD of Wave 2 per founder order.]**

Wave 3 **is** `docs/superpowers/plans/2026-08-20-brand-geometry-tokens-in-the-web-grammar.md`
G1→G4, ratified 2026-08-22 — it stays the implementation plan of record; this
section only binds the carve-outs and one addition:

- **G1 (grammar + theme resolution)** as written: H1 vocabulary (`rounded-button`,
  `rounded-card`, `rounded-badge`, `shadow-brand`, `shadow-card`, `border-w-card`,
  `border-w-divider`, `py-section`, `gap-stack`, `p-card`), kit-resolved at render,
  `derived:` fallback, never a hard failure on a thin kit.
- **G2 (surface.band.* tokens)** as written — closes the `#0D1738` navy gap;
  fixture is the Stripe navy. Dispatchable in parallel with Wave 1 (no Rust).
- **G3 (authoring adoption)** as written, one amendment: the reviewer's
  raw-geometry-on-briefed-kit finding is **advisory prose in the critique**, not a
  diagnostic anywhere.
- **G4 (enforcement walk + phase-2 warning)** amended per carve-outs: the phase-2
  ingest finding ships at **Advice severity** (the `DiagnosticSeverity::Advice`
  variant exists and the ingester has never used it), reaches the agent via the
  normal diagnostics list in tool results and the trace, is **excluded from every
  human-facing surface** (verify the editor/brand-context UI renders nothing new —
  if any UI path renders ingest diagnostics today, it filters Advice), and can
  never reject anything. **H2 phase 3 (hard lint, per-kit strict flag) is REMOVED
  from scope** — not flag-gated, not built.
- **G5 (addition, registered, dispatch after G4's walk):** a web-lane retokenizer
  following the scene precedent (`lumen_agent/retokenize.py` — deterministic rebind
  of raw class values that equal a kit token's value, agent-authored unseeded
  documents only, applied as real invertible ops). Same audience rule: its
  adjustments are trace/agent-visible only.

---

## WAVE 4 — Prove the generation path, then measure everything

*Requires Waves 1–2 landed. Mixed Python; no Rust except nothing-expected.*

### W4.1 — text-to-image proven end-to-end
- **Files:** `apps/api/lumen_api/image_provider.py` (:458 — fetch a plain-`https`
  image URL response instead of erroring `image_model.bad_response`; keep data-URL
  path primary), plus a scripted live run.
- **Behavior + gate:** one live run against a deliberately asset-poor brand (or an
  explicit "generate a hero image" brief) where the director chooses **generate**;
  verify in trace: `generate_image` called, style anchors attached (post-W1 they are
  high-res by construction), aspect hint honored, asset ingested with
  `source.kind=generated`, node references it, reviewer sees it rendering. Cost and
  latency recorded. An honest negative is a valid outcome and blocks W4.3's
  baseline until resolved.

### W4.2 — the imagery decision becomes checkable (deterministic, no model call)
- **Files:** `web_substrate.py` (`finalize_web_run` 4421-4490 gains an optional
  structured `imagery_decision` echo + a census), `prompts_web.py` step 1b (the
  director records its per-band decision through a tiny `record_imagery_decision`
  tool call — same free-prose decision, now ALSO captured as
  `[{band, verdict: place|generate|none, asset_ids?, reason?}]`).
- **Behavior:** at finalize, a deterministic census compares the declared decision
  against the stored document: image nodes per band, registered-but-unreferenced
  assets (the hero-ribbon orphan shape), logo-node presence. Mismatches append to
  the run summary and trace as agent-facing warnings — **not** UI diagnostics, and
  never a failed finalize (carve-outs). The scene lane's dormant rubric machinery is
  explicitly NOT revived; this is the web lane's own thin check, wired into the
  live loop from day one.
- **Tests:** census math on fixture docs (placed/orphaned/missing-logo); finalize
  behavior unchanged when no decision was recorded (edit turns).

### W4.3 — the scoreboard
- **Files:** new `apps/agent_runtime/benchmarks/` (harness + fixtures) — a scripted
  runner over a fixed brand set (Stripe v8-era kit + 2 contrasting ingested brands,
  e.g. one photography-led, one text-forward), each with a pinned brief and a fixed
  generation prompt, executed through the real fleet path.
- **Metrics per run, extracted from artifacts that already exist** (`trace.jsonl`,
  `final_web_doc.json`, the run ledger): image nodes; logo placed (bool);
  generated-image count; rejections by code; error-diagnostic count; author/review
  delegations; wall clock; geometry-utility adoption rate (post-G3); orphaned
  assets; `ladder_gap` presence. Output: one JSON row per run appended under the
  benchmark dir + a compare script that diffs two rows and flags regressions.
- **Gate:** baseline recorded on post-Wave-2 HEAD; every later wave/slice ends by
  re-running the board. This replaces acceptance-walk-as-measurement.

### W4.4 — the iteration-speed debts (infrastructure)
- **C15 fleet worker-version fence:** `clue_fleet/queue.py:~170` lease predicate
  gains a worker code-version stamp (worker registers its version at startup; a job
  leased by a mismatched version is refused loudly). The register calls it the
  highest-leverage infra fix — it manufactured three misdiagnoses in one day.
  Coordinate with the fleet owner (the note at `lumen_api/main.py:370-381` says the
  fence "belongs to the fleet") — if the fleet lane claims it, this slice reduces to
  the design-side version stamp.
- **C17:** pin `LUMEN_CORE_HELPER` in the canonical test invocation docs/recipes.
- **C16:** record `npm ci` in `apps/custom-component-compiler` as the fix for the
  red family (docs/recipe only; no code).

---

## Explicitly out of scope (registered, untouched)

- H2 phase 3 / any strict mode (founder carve-out — removed, not deferred).
- Human-facing surfacing of ANY new diagnostic (carve-out 1). A later product pass
  may design a human "brand-fit report" — that is a new decision, not this plan.
- Scene-lane behavior changes (docs corrections in W2.4 excepted).
- Inline `<svg>` harvesting (register C11), `data-src`/`data-srcset` rungs (C10),
  the geo-redirect junk asset (C12), staged collector for fetch cost (C8) — next
  ingestion wave.
- The exit-judge timeout (C18), Terra `missing_finalize` (C19), proposal-card false
  positive (C20), editor write bugs (C21), `make check` triage (C22) — separate
  owners, unchanged priority.
- Multi-page websites (`HOME_PAGE_ID` fixed) — future charter.

## Verification discipline (every slice)

Red-proof against the recorded failing fixture where one exists (the 2026-08-20 run
traces are the fixture library); suites green WITHOUT the platform `.env`; live
gates run on a single-listener 8010 + freshly restarted fleet worker on HEAD; honest
negatives reported; nothing approved on the founder's behalf; local commits only.
