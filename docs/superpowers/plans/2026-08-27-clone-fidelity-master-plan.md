# Clone-Fidelity Master Plan — verbatim fragments, Ploy-grade output (Phases F0–F5)

> **STATUS 2026-09-03 — PHASE F5 BUILT (engineering); CP3 live walk + founder review OPEN.**
> Executed via SDD on `design/website-multi-page` (22-task execution plan
> `docs/superpowers/plans/2026-09-02-f5-multipage-sites-and-publishing.md`; Opus implementers,
> every diff reviewed and every task re-verified first-hand by the orchestrating session, no
> reviewer subagents per founder rule). Tasks 1–21 + one fix wave landed, local only. Engine:
> route grammar LUMW0036 + AddPage/RemovePage. API: page-aware render, N-page publish served by
> route (`design_web_publish_revision_page` + materialized `design_web_publish_page`,
> migration `6893f29b6973`), PublicSiteAddress from env, workspace handle (`5456c0770de8`),
> Host-matched public pages app. Agent: active page + page tools, one-brief-per-page law,
> R-F5-8 advisory demotions. Shell: real Publish (repository seam), page switcher, page/route
> section, in-editor navigation; dev-shell parity. OPEN: the CP3 acceptance walk (needs a
> live stack + a migrated dev DB: heads must be `5456c0770de8`), the founder review items in
> the ledger (prompt/skill wording; two FLAGGED UI slots; per-page links placement; unpublish
> control; handle default R-F5-5; bare-host root), and the deployment/domain work ruled out of
> scope for now. Ledger: `.superpowers/sdd/2026-09-02-f5-multipage-sites-and-publishing/progress.md`.
>
> **STATUS 2026-09-02 — PHASE F5 SCOPE RE-RATIFIED on `design/website-multi-page`.** Fresh
> scout of the post-F4 tree + founder rulings R-F5-1..5 (URL shape, publish unit, slug/route,
> indexing, workspace handle default). F5 now owns the default-domain serving (Part-IV item 5
> is no longer a gate) and the shell Publish wiring (today a timer-faked dummy). Six lanes
> F5.0–F5.5 replace the four-blocker list; three standing assumptions await ruling at dispatch.
> Execution plan WRITTEN 2026-09-02: `docs/superpowers/plans/2026-09-02-f5-multipage-sites-and-publishing.md`
> (22 tasks across the six lanes, engine first); awaiting founder review, nothing dispatched.
>
> **STATUS 2026-08-29 — PHASE F4 / CHECKPOINT 2 CLOSED (engineering); founder
> acceptance OPEN.** Executed via SDD (Tasks 22–26 = F4.0–F4.4 + Task 27, the founder-rulings
> wave; Opus primaries + Opus-only reviewers; ALL fix rounds orchestrator-implemented per the
> standing split; every round independently reviewed), commits `df09a9d2b..e8355d034`, local
> only. The founder rulings of 2026-08-29 are LAW in the tree: **R-F1** durable noindex
> (migration `4c02d8eac29a`; stamp rides the derive; rollback cannot unindex; clearing is a
> human-only governed tool), **R-X4** keep-flagged degraded-repair default (env toggle;
> never silently the broken original), **R-X9-now** chat-only per-repair release (cascade
> excludes repairs; two-round render-then-ask tool), **R-KIT** attested already true. The
> CP2 walk: 3 real accounts → 3 published co-branded noindex URL-only pages; 16 PASS /
> 2 FAIL / 1 PARTIAL, with T21's deferred proofs landing live (dead-height v2 convicted the
> 6,114px middle-hole band; zero console errors; stated coverage). The two FAILs + the final
> review's cross-task findings were closed by the F4 wave (8 items + round 2) and PROVEN by
> a targeted re-walk (the walk's own dormant fixture now photographs; its exact 124-byte
> sprite refuses; the header is 375-clean; the noindex law's fifth surface closed).
> **Founder acceptance items:** the sealed blind side-by-sides (CP1 + CP2) and the
> consolidated founder package in `f4-final-review.md` (A1–A3, B1–B14 + wave additions).
> Evidence: `.superpowers/sdd/2026-08-27-clone-fidelity-master-plan/progress.md`,
> `task-26-walk-report.md`, `f4-final-review.md`, `f4-wave-review.md`,
> `_memory/2026-08-29-f4-tasks-22-27-close.md`. F5 (true multi-page) remains gated on
> Part-IV item 5; the deferred register with owners is in `f4-final-review.md`
> (`design_create_web_template@1` drift and the multi-file-pytest host wedge are UNOWNED).
>
> **STATUS 2026-08-28 — PHASE F3 / CHECKPOINT 1 CLOSED by founder acceptance.** Executed
> via SDD (Tasks 16–21 = F3.0–F3.4 + the LIVE CP1 walk; Opus primary implementers + Opus-only
> reviewers; SECONDARY fix rounds orchestrator-implemented per founder directive, confirmed as the
> standing split), commits `d20e335dc..0c637dcc7`, local only. Live walk on insighthealth.ai:
> 7 criteria PASS, criterion 1 = the founder's blind side-by-side (OPEN, `/tmp/f3_walk/BLIND/`),
> and the walk's two blocking-class findings — the dead-height extent measure blind to a 6,115px
> middle hole, and dormant activation defeated by the source's own hiding CSS — were fixed in the
> orchestrator's post-final-review wave (dead-height second condition in BOTH detectors; un-hide
> counter-rules at the artifact CSS seam; skipped checks and gate coverage now SAID; meta-CSP
> console error dead). The wave's independent review was in flight at close; the wave's live
> re-walk is DEFERRED BY FOUNDER ACCEPTANCE and rides the F4.4 CP2 walk. Evidence + full rulings:
> `.superpowers/sdd/2026-08-27-clone-fidelity-master-plan/progress.md`, `task-21-walk-report.md`,
> `f3-final-review.md`, and `_memory/2026-08-28-f3-checkpoint1-close.md`. FOUNDER QUEUE carried
> there (headline: role-vocabulary extension; X4/X9 repair-release rulings = F4 entry conditions).
>
> **STATUS 2026-08-28 — PHASE F2 COMPLETE.** Executed via SDD (Tasks 11–15 = F2.1–F2.4
> + acceptance; one fix round per task; final whole-phase review → ONE general fix wave +
> completion round after the FIRST live acceptance walk FAILED on both sites), commits through
> `61fa11db7`, local only. **Re-walk PASS on both named sites**: insighthealth.ai 9 minted /
> 9 approved / 8 previews (1 honest `empty_after_sanitize` refusal — the only refusal reason
> anywhere), stripe.com 10/10/10 previews; all bands bound by probe-skip EVIDENCE (the exact
> hidden section that silently absorbed a band in walk 1 now arrives as a capture record);
> Stripe's `@media`-nested Sohne font fetched and durable (was: one missing font fail-closed
> 100% of the site); labels human; the draft→approve gate and the agent list/insert path proven
> live on both sites; the founder's floor-not-cap ruling honored (mint backstop 40 = capture
> ceiling, never approached). Focused gates green (API 438/438, runtime 84/84; full-suite runs
> founder-waived). Evidence + full rulings ledger + F3/F4 carry register:
> `.superpowers/sdd/2026-08-27-clone-fidelity-master-plan/progress.md`, both walk reports, and
> `_memory/2026-08-28-f2-section-harvesting-complete.md`. FOUNDER QUEUE: reuse-ladder + grammar-
> audit prompt wording (drafts, quoted on real output in the re-walk report); the
> reviewer/exit-judge untaught-about-cloned-sections decision; the hidden-section product ruling.
>
> **STATUS 2026-08-27 (earlier) — PHASE F1 COMPLETE.** Executed via SDD (Tasks 5–9 = F1.1–F1.5 +
> acceptance walk, 5 fix rounds across tasks + one final fix wave; Opus implementers, Opus-only
> reviewers per founder standing rule), commits `1d04b46df..5b68e1b13` (23) on
> `integration/frontend-design-part-iv-v2`, local only. Live acceptance walk: **all 7 criteria
> PASS** — a hand-built fragment renders in-flow with IDENTICAL fragment-markup and CSS digests
> across editor render / agent screenshot / export ZIP / published page; slots substitute (all 4
> kinds); account derive personalizes name/logo/domain through the real route; sanitizer
> red-cases refuse/strip live as ruled; HANDSHAKE OK (stamp `2f8c4edaf3b6`, `FontLicense.basis`
> moved lumen-core). D-F2 Rust obligations landed (real `basis` field, publish gate honors it,
> manifest lists font exclusions + fragment ids + missing digests). Focused suite gate green
> (founder-ruled: no full-suite run at phase close). Evidence + full triage register with owners
> (F2/F3/F4/F5): `.superpowers/sdd/2026-08-27-clone-fidelity-master-plan/progress.md` +
> `_memory/2026-08-27-f1-fragment-engine-complete.md`. Notable F2 carries: status-gate wiring
> (draft/approved read by nothing yet), fragment-vocabulary rename (insert_fragment vs the
> unrelated web_ingest_fragment), Tailwind-scanner amplification ruling, prelude fail-closed
> false-positive ruling, srsset comma-URL case.
>
> **STATUS 2026-08-27 (later still) — PHASE F0 COMPLETE.** Executed via SDD (3 tasks, 5 fix
> rounds, independent review per task, final whole-phase review + one fix wave), commits
> `7c11f0eb6..298abe98d` on `integration/frontend-design-part-iv-v2`, local only. Live acceptance
> walk on insighthealth.ai: **all four criteria PASS** (durable snapshot+screenshot; 212/215
> assets captured with 3 loud drops and 0 silent; Aeonik binaries + ToU embed stamp; mint
> `#30D8A7` seated as `surface.brand` at `basis: declared`). Full apps/api suite: 1054 tests,
> 17 failures — all the pre-existing custom-component family (missing node dep in this
> workspace), zero F0-owned. Evidence trail: `.superpowers/sdd/2026-08-27-clone-fidelity-master-plan/`
> (preserved) + `_memory/2026-08-27-f0-clone-capture-complete.md`. Carried to F1: Rust
> `FontLicense.basis` field + publish exclusions manifest (per D-F2), the F2 deferral register in
> the ledger, and the logo_ladder `url()` fourth-copy defect (needs owner). FOUNDER FLAGS open:
> trial-font embeddability under ToU basis; colombo live-worker shutdown for suite runs.
>
> **STATUS 2026-08-27 (later) — RATIFIED. Founder ruled all §2 decision points (see RULED entries);
> the plan is COMPLETE and awaiting dispatch order. Nothing dispatched yet.**
>
> **STATUS 2026-08-27 — DRAFT, awaiting founder ratification. Nothing dispatched.**
> This plan REWRITES and SUPERSEDES `docs/superpowers/plans/2026-08-25-brand-fidelity-and-logo-ladder-waves.md`
> Waves A/C/K/V per founder ruling 2026-08-27 ("okay to rewrite the plan rather than patching").
> Wave L (target-account logo ladder) is reported built by the founder — its in-tree state must be
> attested before F4 consumes it (verification is F4's first task, not assumed).
>
> Charter: replicate Ploy's clone-based mechanism inside our platform — the client site's sections
> preserved VERBATIM (subtree + scoped CSS + rehosted assets + fonts) and assembled into brand-true
> homepages and ABM campaign pages — per the three founder rulings of 2026-08-27:
> **(R1)** cloned sections are verbatim + slot-editable ONLY (end-to-end editability is future work;
> priority is Ploy-grade output quality); **(R2)** capture scope: homepage first with provisions for
> more pages — checkpoints: CP1 = one perfect cloned homepage → CP2 = target-account campaign pages
> reachable only via explicit URLs (never in nav) → CP3 = new navigable pages; **(R3)** rewrite, not
> patch. Evidence base: the two-part Ploy study (`_memory/2026-08-25-ploy-study-brand-coherence.md`,
> `_memory/2026-08-26-ploy-skills-deep-study.md`) and the two-agent feasibility scout of 2026-08-27
> (engine + platform reports; all file:line anchors below are from those reports, verified on
> `integration/frontend-design-part-iv-v2` — implementers re-verify before editing).
>
> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development, slice by
> slice on founder order. Opus implements; the orchestrating session reviews every diff INLINE.
> TDD throughout. Local commits only, never push, no AI attribution. Rust slices carry the wasm +
> `lumen-api-helper` rebuild ritual (design AGENTS.md §1) + restarts of embedding processes. Design
> tests without the platform `.env`. Never `git stash`. Per repo precedent this master plan fixes
> scope/contracts/acceptance; each phase gets its dispatch-depth execution plan at dispatch.

**Goal:** ingest a client website once and get (a) a published homepage that is byte-faithful to the
client's real site, and (b) target-account ABM campaign pages assembled from the same cloned
sections plus token-lawful new sections, personalized via slots (including the target-account logo),
published at explicit-URL-only routes — with the editor offering slot-level editing on cloned
sections and full editing on new sections.

---

## §0. The feasibility verdict this plan is built on (2026-08-27 scout)

**RULED (pending founder confirmation): a NEW WEB NODE KIND — `Fragment` — not the custom-component
channel.** The custom-component channel is structurally unable to host verbatim fragments: source
must be TSX (`custom_components.py:41,149`), `dangerouslySetInnerHTML` is a compile error
(CCC0116, `analyze.mjs:451-463`), `<style>`/CSS imports are forbidden (CCC0117/0101), the CSS
pipeline is Tailwind v3.4.17 closed-config that cannot carry third-party CSS (`build.mjs:197-239`),
and rendering is an opaque-origin `sandbox` iframe outside page flow (`render.rs:680`,
`custom_component_runtime.py:736-742`). Reversing any of those gates guts the channel's security
model for its existing purpose. Every one of those properties is the opposite of what a cloned
in-flow section needs.

The new-node-kind path has complete precedent coverage:
- **Deliberately-unsanitized verbatim content in the doc model:** `Embed{provider: Custom, html}`
  (`ops.rs:232-233` — "html is NOT sanitized: embeds are sandboxed by design").
- **Arbitrary CSS surviving render → export → publish untouched:** `WebDoc.custom_css`
  (`render.rs:231-236`; only `@import`/`javascript:`/`</style` blocked, `validate.rs:62-73`) and
  the API-supplied CSS splice seam `WebThemeOptions.font_face_css` (`theme.rs:174-175, 665-668`).
- **API-resolved per-node content handed to the pure engine render:** the custom-component runtime
  frame map (`render.rs:626-746` + `custom_component_runtime.py`).
- **HTML-level marker substitution that preserves everything else verbatim:** `substitute_vars`
  (`derive.rs:650-751`, quick_xml walk, copies unknown content through, re-derivable).
- **Immutable content-addressed artifact registry with reference-integrity gating:** the
  custom-component artifact tables (`86a9ce389e6e`) + `design_store.py:1420-1525`.
- **Published-page CSP already permits inline styles** (`style-src 'unsafe-inline'`,
  `web_export.py:759-774`) — fragments' scoped CSS is deliverable — while `connect-src 'none'`,
  `img-src`/`font-src` single-origin, and `form-action 'none'` make **full asset rehosting
  mandatory** (which is the Ploy move anyway) and give a backstop under our sanitizer.

**The one genuinely new security obligation:** in-flow rendering means fragment bytes reach the
published DOM, and the export path has **no sanitizer at all** (scout §5); the published CSP even
permits inline `<script>` (`script-src 'unsafe-inline'`). Therefore fragments are sanitized **once,
at artifact creation** (F1.2) — and because the node carries only an artifact id (never raw HTML),
the ops write path stays clean by construction (the `canonicalize_incoming_kind` arm validates id
shape only, exactly like `CustomComponent`).

---

## §1. Ruled architecture (the shape every phase serves)

**The fragment artifact** — immutable, content-addressed, workspace-scoped, stored like custom
components (registry row + bytes in the design blob namespace `{ws}/design/{sha}`):

```
design_web_fragment (fragment_id "frag_<sha256-16>", workspace_id, source_kit_id/version,
                     source_url, section_role,          -- hero|nav|footer|proof|testimonial|…
                     label, status, created_at, provenance_json)
fragment artifact payload (content-addressed, immutable):
  html            -- SANITIZED subtree; slot markers annotated (data-lumen-slot="key")
  css             -- source rules scoped under .lumen-frag-<id> (+ media queries preserved)
  asset_digests[] -- every referenced image/font digest (already rehosted via F0)
  slot_manifest   -- key → {kind: text|image|href|visibility, fallback}
  preview_digest  -- section screenshot for editor/agent pickers
```

**The node** (engine): `WebNodeKind::Fragment { fragment_id, slots: BTreeMap<String, FragmentSlotValue> }`
— a **leaf** (like `CustomComponent`), slot values are flat scalars (text / asset_id / bool),
rendered **in-flow**: `<div class="lumen-fragment lumen-frag-<id>" data-node-id=…>{substituted html}</div>`.
The engine's render receives resolved fragment content via a render-options map (the
custom-component frame-map precedent) so `render_web_doc` stays pure; the API resolves artifacts
by digest. Fragment CSS is concatenated by the API and spliced via a new `WebThemeOptions.fragment_css`
(the `font_face_css` precedent) — per-fragment identity retained, `custom_css` untouched.

**Why artifact-pinned, not inline HTML** (D-F1 below, recommended): fragments are 5–50KB+ and
**shared across documents** — one cloned nav serves fifty ABM account pages; content-addressing
dedups them, ops diffs stay small, sanitization happens exactly once, and the existing
reference-integrity gate pattern applies.

**Editability = R1 by construction:** a leaf node cannot be restructured; the editor's unknown-kind
fallback already degrades to generic cards (dev shell: Spacing/Personalization/Classes,
`WebInspectorPanel.tsx:544-641`; FE adapter: `layoutOnly` container, `hydrate.ts:173-177`); the
bridge's kind **allowlists** (`web_bridge.py:1199-1240`) make it non-resizable/non-droppable by
default. A dedicated fragment inspector card (slot values from the manifest) lands in F3.

**Publishing shape per checkpoint (R2):**
- CP1: today's model exactly — one document, page `home`, one slug. **No publish-layer work.**
- CP2: **one document per account** (the existing batch derive+publish machinery,
  `main.py:4426-4636`) at flat slugs `abm-<account>`; URL `/w/{ws}/p/{slug}` (the O6b interim
  scheme). Pretty `/abm/<account>` paths belong to Part-IV item 5 (tenant-subdomain v1, founder-
  ruled, unbuilt) — **out of this plan's scope, recorded as the CP2 URL-polish dependency.**
  This plan adds the missing `noindex` publish option (robots meta at package build).
- CP3: true multi-page (AddPage/RemovePage ops, page-aware render/publish/agent, nav resolution)
  — **F5, explicitly last**, after Part-IV routing exists to serve it. The provision R2 asks for
  is structural, not built early: fragments are document-independent, and `WebDoc.pages` +
  `derive_web_doc` are already N-page-correct (`validate.rs:32-58`, `derive.rs:195`); the
  hardcoded-`"home"` sites are enumerated in F5 so nothing new hardcodes more of them.

---

## §2. Founder decisions — RULED 2026-08-27

- **D-F1 — fragment storage: RULED — artifact-pinned.** Immutable content-addressed fragment
  artifacts + id-only nodes, per §1. (Inline-HTML-in-node rejected.)
- **D-F2 — cloned fonts at publish: RULED — embed permission rides the platform Terms of Use.**
  The workspace's acceptance of the platform ToU includes permission to embed the font families
  ingested for its own brand. Implementation: ingestion stops hardcoding `embeddable: False`
  (`emit.py:255-266`) for workspace-brand fonts and instead stamps
  `{embeddable: true, basis: "platform-terms"}` while keeping the license *name* honest
  (`unknown`/hint preserved) and a restrictions note for print/off-platform reuse; the publish
  gate (`web_export.py:235-244`) honors the basis field; the publish manifest **stops discarding
  the exclusions list** (`web_export.py:966`) so anything still dropped is always visible.
  The ToU text itself is a founder/legal deliverable outside this plan — F1.5 lands the
  mechanics, and the flag flips per workspace only where the ToU basis applies.
- **D-F3 — fragment mobility: RULED — Option A, top-level reordering only.** A whole fragment
  (hero, testimonial, proof band) can be moved up/down the page. It can NEVER be: manually
  resized; a drop target for ordinary nodes; internally re-laid-out; or detached into editable
  nested elements. Mechanically: `Fragment` joins `movable_kinds`, stays out of
  `resizable_kinds`/`parent_kinds` (`web_bridge.py:1199-1240`), remains a leaf in the engine.

  **Amended 2026-09-04 (R-A6, founder):** a human may also edit the TEXT of ONE element inside a
  clone — its plain text, bold/italic/underline, and a −3…+3 relative size step — and nothing
  else. Mechanically this is not a hole in Option A: the edit is a per-instance `text_overrides`
  entry ON the fragment node, keyed by the element's structural path inside the clone, applied at
  render AFTER slot values; the harvested artifact is never rewritten, and no other instance of
  the same clone is touched. The fragment stays a leaf, stays out of
  `resizable_kinds`/`parent_kinds`, and is otherwise still movable-only — nothing inside it
  becomes a selectable, draggable, or re-layoutable node. So the ruling now reads: a clone moves
  as a whole and exposes slot values AND per-element text overrides; nothing else inside it is
  editable. Spec:
  `docs/superpowers/specs/archive/2026-09-04-web-editor-annotations-and-clone-text-edits-design.md` §3.6.
- **D-F4 — sanitizer strictness: ADOPTED BY DEFAULT (not explicitly ruled; reversible on founder
  word):** strip `script`, `on*` handlers, `iframe/object/embed/form/meta/base/link`,
  `javascript:`/`data:` hrefs; every `src/srcset/url()` must resolve to a rehosted digest —
  **fail-closed**: an unrehostable reference refuses fragment creation rather than silently
  dropping. Inline SVG preserved (scrubbed of scripts/handlers).
- **D-F5 — CP2 slug shape: RULED — flat pilot slugs now** (`/w/{workspace}/p/abm-goodman-campbell`
  pattern). One derived document per account; each page accessible only through its explicit URL,
  absent from all site navigation, marked `noindex`, and tracked separately in the batch
  publication manifest. Accepted disadvantage: less elegant URL until Part-IV item 5
  (tenant-subdomain serving) lands — recorded as the CP2 URL-polish dependency, not a blocker.
- **D-F6 — the clone-repair ladder: RULED 2026-08-28 (founder; amends the F2-era "never edit a
  cloned section's internals" law, which protected brokenness).** Governing principle, verbatim:
  *"A clone is the starting reference, not an untouchable artifact. Never preserve a broken
  result merely because it came from the original site."* When a cloned section is broken, the
  agent repairs in order: **(1)** reproduce the original experience with supported primitives;
  **(2)** build an equivalent interaction serving the same storytelling purpose; **(3)** a
  deliberate, compact static fallback — artificial scroll height removed entirely; blank dead
  space is never acceptable. Whatever the rung, the repair preserves: content hierarchy and
  order, typography and colors, image treatment, proportions and density, spacing, section
  rhythm, the interaction's storytelling purpose, and the brand's character — the Brand Grammar
  Audit governs the adaptation. **Mechanics:** the harvested original stays IMMUTABLE (evidence),
  marked `degraded` with the reason; the repair is a NEW fragment carrying `derived_from` +
  reason provenance; the page pins the repaired one. Amended law: *"Never casually rewrite a
  working cloned section. When a clone is visibly or functionally broken, preserve the original
  artifact and repair, rebuild, or replace it through the clone-repair ladder."* Expectation
  set honestly: rung 1 is often unreachable (the engine's interaction vocabulary is deliberately
  bounded); rungs 2–3 are the common case, as with Ploy.
- **D-F7 — the review function: RULED 2026-08-28 (founder).** Clone/audit review knowledge lives
  in a SHARED RUBRIC artifact, never inside one agent's private prompt: soft on minor
  differences (animation timing), STRICT on brokenness (blank space, missing content, broken
  controls, unusable height, invisible elements, failed mobile behavior), STRICT on brand
  coherence after repair (measured spacing, density, typography, colors, rhythm). A
  fast-loop-style flag (scene-lane precedent: reviewer removed, orchestrator self-reviews,
  ~2× faster) quarantines the separate reviewer agent; the orchestrator then self-reviews
  against the SAME rubric. The flag changes WHO checks, never WHAT is checked.
- **D-F8 — hidden source sections: RULED 2026-08-28 (founder) — mintable-but-dormant.** A
  section the source site hides is: preserved with "hidden on source site" provenance; NEVER
  auto-approved by the kit cascade; excluded from default agent discovery; shown in the
  fragment inspector as "hidden on source site"; activated only by a human; activation requires
  a usable preview. Agent behavior: a dormant section never appears on a generated page by
  default and the agent never proactively offers it — it surfaces only when the user asks for
  something it serves.

---

## Phase F0 — clone capture substrate (Python, `lumen_ingestion`; no Rust)

The raw material. Website ingestion stops discarding what the clone needs.

- **F0.1 Persist the snapshot.** `SiteSnapshot` HTML + all fetched stylesheets + the full-page
  screenshot stored durably under `{ws}/design/{sha}` keyed from the ingestion job (today the
  snapshot dies in memory — only `BrandEvidence` persists, `pipeline.py:961`). The screenshot
  becomes the reference image for the F3/F4 review gate.
- **F0.2 Total asset slurp.** Every `<img>`/`srcset`/`<picture>` rung, CSS `url()` background,
  inline-SVG-referenced asset, and **font binary** fetched and rehosted with provenance-preserving
  names; caps replaced by budget policy with loud diagnostics ("no silent caps"); the known
  scorer/fetcher pool mismatch and `raise_on_error=False` silent drops closed pipeline-wide.
  Per ruled D-F2, workspace-brand font entries are stamped `{embeddable: true,
  basis: "platform-terms"}` at emit (replacing the hardcoded `embeddable: False`,
  `emit.py:255-266`), license name/hint preserved honestly.
- **F0.3 Source-truth styling.** Declared CSS custom properties captured as role declarations
  (0.9 confidence, above heuristic clustering); `:hover/:focus/:active` rules for interactive
  selectors extracted from the persisted CSS; `prefers-color-scheme: dark` blocks captured. Fix
  the two known parser crashes (`var()` cycle; `rgba(... / var())`) while in the file.
- **F0.4 Multi-page provision (capture only).** The capture entry accepts a page list (homepage
  v1; nav-linked same-domain pages later) — one snapshot record per page, same job. No consumer
  beyond F2 yet.

**Acceptance:** re-ingesting a Webflow-class site yields a durable snapshot + screenshot; 100% of
referenced assets have bytes-or-loud-error; fonts have binaries; declared variables arrive as roles.

## Phase F1 — the Fragment engine substrate (Rust + Python; the hard core)

- **F1.1 Node kind (Rust).** `WebNodeKind::Fragment` per §1: `doc.rs` variant + `kind_name` +
  leaf ruling; `validate.rs` arm (fragment_id shape, slot key/value bounds); `ops.rs`
  `canonicalize_incoming_kind` arm (id + scalar validation only — no raw HTML in the doc);
  serde round-trip gives insert/move/duplicate/undo free. `SetNodeProps` updates slot values.
- **F1.2 Fragment registry + sanitizer (Python).** `design_web_fragment` table (hash-id alembic
  migration, single head) + artifact payload per §1; the **one-time sanitizer** per D-F4 (modeled
  on `inline.rs`'s never-fails allowlist + `ops.rs:186-290`'s write-path invariant, but
  fail-closed on unrehostable references); CSS scoper (prefix every selector under
  `.lumen-frag-<id>`, preserve media queries, strip `@import`); slot-marker annotator.
  Reference-integrity gate on doc writes (extend `design_store.py:1420-1525` pattern).
- **F1.3 Render integration.** API resolves fragment artifacts → render-options fragment map;
  engine render arm emits in-flow wrapper + substituted HTML; `fragment_css` splice through
  `WebThemeOptions` → head, **before** compiled `site.css` (compiled Tailwind wins ties —
  acceptable because fragment selectors are scoped; recorded as a watched risk). Both preview
  paths (editor render route `main.py:3245+`, agent `render_web_preview`) thread the map.
- **F1.4 Slot substitution + derive.** Substitution walk modeled on `substitute_vars`
  (`derive.rs:650-751`): replace `data-lumen-slot` marker content with bound text / swap image
  digest / swap href / drop subtree on visibility=false; markers preserved (re-derivable).
  `apply_slots` arm so **account derive binds fragment slots** — `account_values()`
  (`main.py:9276-9317`) then personalizes cloned sections with zero new plumbing (name, domain,
  logo → the ladder's asset).
- **F1.5 Export/publish integration.** `web_export.py`: fragment asset digests join the asset
  walk (fixing the class of gap `_image_asset_ids` has — and closing the recorded background-image
  ZIP gap at the same seam); fragment CSS into the static package; publish manifest lists
  fragment ids + stops discarding font exclusions (D-F2). Full ritual: cargo workspace, helper +
  wasm rebuild, HANDSHAKE, both Python suites.

**Acceptance:** a hand-built fragment artifact renders in-flow, pixel-stable across editor
preview / agent screenshot / export / published page; slots substitute; derive personalizes;
sanitizer red-cases (script, onclick, remote img, form) all refuse or strip as ruled.

## Phase F2 — section harvesting (the Ploy transliteration, done our way)

- **F2.1 Segmentation.** From F0's persisted snapshot: section boundaries + roles
  (nav/hero/proof/testimonial/security/footer) via landmarks + the measured band sequence.
- **F2.2 Fragment minting.** Per section: subtree extraction → sanitizer → CSS scoping (rules
  matched to the subtree from the persisted stylesheets, media queries kept) → asset digest
  rewrite → **automatic slot detection** (headline/paragraph text nodes, `<img>` slots, CTA
  label+href, section visibility — Ploy's shallow-refactor surface, extracted mechanically) →
  preview screenshot → registry row bound to kit version. Human gate: fragments ride the kit
  approval surface (draft kit → approve), consistent with the existing brand-context flow.
- **F2.3 Agent access.** Fragments in `search_assets`-style discovery + an `insert_fragment`
  authoring action (web lane); prompt/recipe vocabulary ("reuse cloned sections for chrome and
  proof; compose new sections only where no fragment serves the job" — the reuse ladder).
- **F2.4 Brand Grammar Audit artifact.** The extracted grammar (type treatment, cadence,
  color-frequency rules, surface language, anti-pattern blacklist) written per kit, injected into
  web-lane prompts to govern NEW sections (the Ploy Define/Build rules; extends BrandBrief).

**Acceptance:** ingesting insighthealth.ai or stripe.com yields ≥5 approved fragments with slots
and previews; the agent can list and insert them.

## Phase F3 — CHECKPOINT 1: one perfect cloned homepage (AMENDED 2026-08-28 per D-F6/D-F7/D-F8)

- **F3.0 Substrate deltas for the three rulings** (one migration; the F1 immutability discipline
  unchanged): fragment status vocabulary gains `dormant` (D-F8) — minted for hidden-on-source
  sections (probe-skip/outside-root class evidence) instead of dropped-or-offered, never
  cascade-approved, excluded from default discovery, human-activated only, activation requires
  a usable preview; a `degraded` marker + reason on originals and `derived_from` + reason
  provenance on repairs (D-F6); **dead-height detection at mint** (section height vastly
  exceeding visible content ⇒ born `degraded` with reason — the repair ladder's trigger).
- **F3.1** Chat-driven walk: "recreate our homepage" → agent assembles fragments in source order,
  fills slots, adds nothing; **degraded clones go through the D-F6 repair ladder** (compose the
  replacement under the Grammar Audit → mint as a derived fragment → pin the repair, lineage
  recorded); publish at one slug. The reuse-ladder prompt law is amended to D-F6's wording.
- **F3.2** Fragment inspector card (slot values: text fields, asset picker, visibility toggles;
  dev shell first, FE parity after) + D-F3 mobility ruling wired into the bridge allowlists +
  D-F8 affordances ("hidden on source site" display, human activation with preview) + the
  degraded→repaired lineage visible.
- **F3.3** The review gate — **behavioral, not just pixel** (D-F6's detector half + D-F7's
  rubric): full-page screenshot vs F0's reference PLUS scroll-through capture (interaction
  states at several positions), mobile viewport, console errors, artificial-height-collapse
  check, reduced-motion; the SHARED clone-review rubric artifact (soft on minor differences /
  strict on brokenness / strict on post-repair coherence) consumed by the reviewer agent — and,
  behind the **fast-loop flag**, by the orchestrator self-reviewing with the reviewer
  quarantined (D-F7); structured critique agent-facing, advice-only per standing carve-outs;
  a blind side-by-side as the founder acceptance walk.
- **F3.4** F2 quality carries (bounded wave, not scope creep): compound-band segmentation
  refinement; role-recall re-measure on real inventory; CSS byte + preview-bytes budgets;
  the prose round (grammar-audit wording per founder direction, n≥2 dark wording, implausible-
  leading abstention); ledgered minors (LUMW0606 split, diagnostic id escaping, fragmentless
  second-render guard, duplicate-pin instance drop).

**Acceptance (CP1):** a published page a reviewer cannot reliably distinguish from the client's
real homepage at 1440px; fonts present (per D-F2 ruling); every asset served from our origin;
zero console errors; **no dead scroll-height regions — every degraded clone repaired through
the ladder with lineage recorded (D-F6)**; dormant sections absent from the page and from
default discovery yet visible in the inspector (D-F8); the review gate exercises the behavioral
walk under the shared rubric in BOTH flag states (D-F7); homepage remains re-derivable
(markers intact).

## Phase F4 — CHECKPOINT 2: ABM campaign pages, explicit-URL-only

- **F4.0** Attest the logo-ladder's in-tree state (Wave L slices; scene bridge included or not);
  record findings before consuming.
- **F4.1** Campaign shell fragments: page-local minimal header (seller mark + "Prepared for
  <account>" + one CTA) and legal-only footer, minted as fragments with account slots — never the
  cloned global nav (every nav link is an escape route; the Ploy campaign-shell rule).
- **F4.2** The assembly recipe: cloned chrome + personalized hero (slot-bound) + token-lawful new
  sections (`abm-*`) under the Grammar Audit; seller-dominance rules (exact target logo via the
  ladder, one restrained accent, "would it still look like the seller's site without the target
  logo?" as a review question); relationship-language guardrails in the prompt (Prepared-for
  framing; no partner/customer claims).
- **F4.3** Batch personalization + publish: existing derive+batch machinery, flat slugs
  `abm-<account>` (D-F5), **`noindex` robots meta** added to the publish package for account
  pages, publish state readable per account on the batch manifest.
- **F4.4** CP2 acceptance walk: pick 3 real accounts → 3 published pages, each co-branded,
  noindex, reachable only by URL, passing the F3.3 coherence gate against the seller reference.

## Phase F5 — CHECKPOINT 3: true multi-page + real publishing (SCOPE RE-RATIFIED 2026-09-02)

> **Supersedes the 2026-08-27 provision below (kept for the record).** Re-scouted 2026-09-02 on
> `design/website-multi-page` against the post-F4 tree; founder ruled the five publishing
> decisions the same day. F5 is **no longer gated on Part-IV item 5** — the default-domain
> serving IS an F5 lane now. Own dispatch-depth execution plan follows; nothing dispatched yet.

**Charter.** A web document is ONE SITE with N pages. The user (or the agent) adds pages, edits
each page's route, and clicks Publish in the platform shell; the whole site goes live on our
own domain at `{workspace-handle}.pages.cluehq.ai/{site-slug}{page-route}`. Custom domains are a
named follow-on (premium), designed for but not built.

**Founder rulings 2026-09-02 (LAW):**
- **R-F5-1 URL shape:** tenant subdomain per workspace (re-affirms the Part-IV tenant-subdomain
  v1 ruling); site slug + page route as the path. Public base comes from CONFIG (env-parity
  rule), never from the request host.
- **R-F5-2 Publish unit = the SITE.** One Publish publishes every page under one slug, each
  live at its own route. No per-page publish state.
- **R-F5-3 Slug vs route:** the share dialog's slug field IS the site slug; the home page's
  route stays `/`, so the site answers at the bare slug.
- **R-F5-4 Indexing:** existing law holds — ABM pages `noindex` and durable (R-F1); ordinary
  sites follow the dialog's indexing toggle.
- **R-F5-5 Workspace handle — DEFAULT SET BY THE PLAN, founder to confirm at dispatch:**
  auto-derived from the workspace/brand name, owner-editable until the first publish,
  immutable after (a rename after first publish is a future redirect feature, not a v1 knob).

**Further founder rulings 2026-09-02 (LAW):**
- **R-F5-6 CP3 v1 product target = the per-account ABM microsite** — a landing page plus
  supporting pages, site-internal nav, still `noindex`. Reuses every CP2 mechanism.
- **R-F5-7 Page material:** new pages are composed from the homepage section library plus
  token-lawful new sections. **Multi-page CAPTURE of the client's real subpages is a separate
  follow-on on a separate branch** — never part of F5.

- **R-F5-8 Links: structural freedom, guidance only (RULED 2026-09-02).** In the structural
  and mechanical sense a page may link to ANY page — site-internal routes and off-site
  destinations alike. No gate refuses a link by destination. The agent is only PROMPTED and
  EXPLAINED (skills + tool strings) that actively linking off an ABM campaign page is not good
  practice: one visitor, one argument, one CTA. Consequences for the F4 machinery, to land in
  F5.4: the by-role refusal of cloned `nav`/`footer` on ABM pages (`ESCAPE_ROUTE_ROLES`, R24-1)
  and the campaign-shell one-anchor shape gate (`fragment.shell_escape_route`, R23-3) are
  DEMOTED from refusals to advisory notes in the tool result; the publish-manifest escape-route
  audit stays exactly as it is (it already only reports). Unchanged: `noindex` stays durable
  law (R-F1), the sanitizer's scheme rules (`javascript:`/`data:` still stripped) are security,
  not policy, and stay.

**The six lanes (replaces the four-blocker list):**
- **F5.0 Engine page ops.** `AddPage` / `RemovePage` (invertible, envelope-ready, in
  `crates/lumen-web/src/ops.rs` beside the existing `SetPageMeta`), a route GRAMMAR in
  `validate.rs` (leading `/`, lowercase segments, no trailing slash, reserved names such as
  `manifest.json` refused; today only duplicates are refused). wasm + `lumen-api-helper` rebuild
  ritual. (The old blocker (b), the replay gate, is NOT separate work: ops carry `page_id` and
  the gate replays whatever the engine accepts.)
- **F5.1 Page-aware render / preview / review.** `page_id` on `GET /documents/{id}/web/render`,
  the editor iframe fetch (`engine/webDocuments.ts::fetchWebRenderHtml`), `render_web_preview`
  (all three widths + state captures) and `review_cloned_page`; the `"home"` literals in
  `main.py` (render ~3594–3686, turn targets ~8672, turn fragment package ~8840) and the bridge
  default (`web_bridge.py:1250`) go; the thumbnail stays first-page.
- **F5.2 N-page publish + serving.** The publish package renders every page; storage keyed
  `(workspace, slug, route)` (a page table beside `design_web_publish`, one-step rollback
  preserved); serving at `/{slug}` and `/{slug}{route}`; site-internal hrefs rewritten to the
  served path; the manifest lists pages; `HOME_PAGE_ID` leaves `web_export.py`.
- **F5.3 Shell publish + default domain.** The DESIGNED share menu (slug, indexing toggle,
  description, custom-HTML tab — presentation truth already exists) stops faking: a platform BFF
  proxy for publish / unpublish / state read, the `clue:artifact-publish-request` timer replaced
  by the real call, publish state read back per artifact. Then the domain: workspace handle
  (R-F5-5), config-sourced public base, a host→workspace RESOLVER TABLE in front of the existing
  serving route (so a custom domain later is one more row + verification + TLS), wildcard DNS +
  TLS. Ships shell-wiring-first on the interim `/w/{ws}/p/{slug}` route, domain second.
- **F5.4 Agent page vocabulary.** `LumenWebTools.page_id` becomes an ACTIVE page (one
  assignment; ~40 tool sites already read `self.page_id`); add/list/switch-page tools; the
  "page_id is ALWAYS home" tool strings and the single-page skill text (create-website,
  edit-website, campaign-page-workflow) amended; **one author delegation per page and the
  mutation budget reset per page render** (the 14-per-round budget and delegation state loss
  measured on the 2026-09-01 OpenAI run would otherwise multiply per page).
- **F5.5 Route editor.** A page-route control in the shell inspector (needs a designed slot per
  the presentation-truth rule — flagged for the dummy frontend) wired to `SetPageMeta`; dev-shell
  parity.

**Acceptance (CP3):** from a project chat, the agent builds a ≥3-page ABM microsite for one
real account in one leg; the user edits one page's route in the inspector; Publish in the
platform shell puts the whole site live at `{handle}.pages.cluehq.ai/{slug}` with every page at
its route, site-internal nav working, ABM pages `noindex`; unpublish takes it down; the F3.3
behavioural gate runs on every page.

**Deferred, named:** custom domains (premium; resolver table receives them); multi-page
capture of the client's real subpages; workspace-handle rename with redirects.

### Original 2026-08-27 provision (superseded, kept for the record)

Scope-ratified only; own execution plan when its turn comes, and **gated on Part-IV item 5**
(tenant-subdomain serving) for real routes. The four independent blockers to clear, enumerated by
the scout: (a) `AddPage`/`RemovePage` ops (`ops.rs:53-129` has none); (b) the agent replay gate
(`main.py:8884-8899`); (c) the hardcoded-`"home"` sites (render `main.py:3300,3326`; publish
`web_export.py:70,333-338,973`; substrate `web_substrate.py:112,744`; bridge `web_bridge.py:1243`;
turn-targets `main.py:7769`); (d) one-slug-one-document publish (`design_store.py:1244`) +
`page.route` read by nothing. Until F5, "more pages" = more documents — which CP2 already proves.

---

## Cross-cutting register

- **Never-synthesize (logo + assets)** carries over from the superseded plan as permanently
  binding: no redrawn wordmarks, no recolored logos, no fabricated screenshots; an empty slot is
  correct, a fabricated asset is the failure.
- **Security posture:** sanitize-once at fragment creation (immutable artifact) + id-only nodes +
  published CSP as backstop; the sanitizer's red-case suite is a hard exit gate of F1.
- **`/asset-store` cross-tenant serving** (ruling R-D4-7) now fronts entire cloned sites; the
  existing "content addressing is not authorization" residual gets louder — cross-reference the
  standing [B2×presign] policy bullet; no change in this plan, recorded.
- **Cascade risk:** compiled `site.css` lands after fragment CSS; scoped selectors should shield
  fragments, but a Tailwind utility name colliding with a cloned class is possible — F1.3 adds a
  fixture pinning the order and a diagnostic if a fragment class is also a live utility.
- **Alembic:** hash ids, single head; the phase-C multi-head situation is owned elsewhere.
- **Process:** Opus implements / orchestrator reviews inline; design full suite as one background
  run per slice close; focused tests inline (standing memory rules).
