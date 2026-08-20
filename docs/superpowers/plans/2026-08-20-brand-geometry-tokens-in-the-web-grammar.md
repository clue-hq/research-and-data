# Brand Geometry Tokens in the Web Class Grammar — Ratified Plan (the enforcement mount)

> **STATUS 2026-08-20 — REGISTERED; awaiting founder ratification of H1–H4, then
> slice-by-slice dispatch.** Charter: the founder's enforcement question ("we already
> have a natural system for color tokens and typographic tokens — can we make brand
> tokens for stroke width, corner radius, and the other brand-geometry things? It's
> the token system itself that makes the quality 10× better for the agents, right?")
> and the controller's answer the founder confirmed: promote measured geometry from
> advice to law by extending the web class grammar with kit-resolved geometry
> utilities, the way color already works. This is the design-brief plan's registered
> follow-up ("tier 3.5"), sequenced AFTER its coherence walk — deliberately, so the
> walk's evidence prices what enforcement adds.
>
> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development,
> slice by slice on founder order. **Process rule (founder, binding): Opus agents
> implement; the orchestrating session reviews every diff INLINE itself.** TDD
> throughout. Local commits only, never push, no AI attribution. Design tests WITHOUT
> the platform `.env`. **This plan touches Rust** (`crates/lumen-web`) — every engine
> slice carries the wasm + `lumen-api-helper` rebuild ritual (the design subsystem's
> AGENTS.md §1) and restarts of every process that embeds the helper. Never `git
> stash` (global refs/stash across worktrees). Anchors verified 2026-08-20 at
> `550d8f4f`; re-verify before editing.

**Goal (the founder's sentence):** the agent physically cannot be off-brand on
geometry — radius, stroke, shadow, spacing resolve from the kit's measured tokens
through the class grammar itself, exactly like `bg-primary` resolves color — so the
brief only has to say *where* things go, and the agent's whole attention budget moves
to composition.

---

## 1. The evidence base (why now, and what the walk already proved)

From the design-brief plan's live coherence walk (2026-08-20, Stripe v6):

- **Theme-owned surfaces already obey measured geometry mechanically.** Every
  generated button computed `border-radius: 4px` — the measured `radius.button` —
  because buttons are styled by the theme, not by author classes. Where geometry
  flows through a mechanical channel, fidelity is total. This is the plan's thesis
  already working on the one surface that has the channel.
- **Free-layout geometry held by brief + reviewer — at n=1.** The band rhythm
  matched exactly and cards behaved, but nothing *mechanical* stops `rounded-2xl`
  (16px) on a 6px-radius brand; that walk's fidelity rests on prompt discipline and
  one sighted review round. Enforcement is the difference between "held today" and
  "cannot drift".
- **The scene engine is precedent, not speculation:** `rd($radius.card)`,
  `stroke($border.default, $stroke.width.card)`, `$space.*`, governed by `LUMB0806`
  (raw spacing/radius/stroke → "use the token"). The web grammar simply never got
  the same treatment — it hard-enforces color only (`LUMW0210/0211/0212`).
- **The unnameable-color gap is the same disease:** Stripe's real navy statement
  band (`#0D1738`) has no kit token, so the walk's agent used `bg-dark` and filed a
  `ladder_gap`. Geometry tokens without surface tokens for measured band colors
  would leave rhythm half-enforceable.

## 2. Verified anchors

- **The web class grammar:** `subsystems/clue-design/crates/lumen-web/src/classes.rs`
  (the allowlist — `"rounded", "rounded-"` etc. — and the color-token law's home);
  theme resolution in `crates/lumen-web/src/theme.rs`; diagnostics of the LUMW02xx
  family surface through ingest (`create-website` documents the codes).
- **The kit carries measured values now** (design-brief slice 2): `radius.*`,
  `stroke.width.*`, `shadow.*`, `space.*` with `website:` provenance and `derived:`
  fallbacks — groups MIX rungs; consumers read provenance per token.
- **Recipes already speak token names** (slice 3): `component_recipes[]` reference
  `radius.button`, `space.md`, `surface.brand` — the authoring-side vocabulary this
  grammar extension makes literal.
- **The rebuild ritual:** any `lumen-web` change → wasm rebuild + helper rebuild +
  restart of the design API and every fleet worker embedding `LUMEN_CORE_HELPER`
  (this week's genweb work deliberately touched no Rust; this plan is where that
  changes).

## 3. Founder decisions (H1–H4 — rule before slice 1)

- **H1 — the utility vocabulary.** Proposed: semantic, role-shaped names mirroring
  the kit's token roles — `rounded-button`, `rounded-card`, `rounded-badge`,
  `shadow-brand`, `shadow-card`, `border-w-card`, `border-w-divider`,
  `py-section`, `gap-stack`, `p-card` — resolved from the pinned kit at render,
  `derived:` fallback when unmeasured (never a hard failure on a thin kit).
  *Recommendation: as proposed; small closed set in v1, grown by registration.*
- **H2 — rollout posture.** Proposed: **soft-first.** Phase 1 the utilities exist
  and recipes/prompts prefer them; raw `rounded-*`/`shadow-*` stay valid. Phase 2
  an ingest WARNING on raw geometry when the kit carries a brief. Phase 3 the
  strict `LUMB0806`-style HARD error — gated per kit (a flag on the kit, ruled by
  the founder when a brand wants law), so existing documents keep editing cleanly
  forever. *Recommendation: as proposed; strict-mode default is a later product
  decision, not this plan's.*
- **H3 — surface tokens for measured band colors** (the navy gap). Proposed: the
  slice-2 measurement mints `surface.band.*` (or extends the kit's semantic color
  set) for recurring measured band colors, ingestion-side, so briefs and the
  grammar can NAME the rhythm's surfaces. *Recommendation: yes, in this plan
  (slice G2) — geometry enforcement without nameable surfaces is half a law.*
- **H4 — typography's escape hatch.** `text-[51px]` still slips the grammar (the
  signature-moment escape). Proposed: leave it in v1 (the craft skill's
  signature-moment discipline governs), revisit only if walks show scale drift.
  *Recommendation: leave; one escape with a named ritual is honest.*

## 4. Slices (each on founder order, sized like the prior plans')

### Slice G1 — the grammar + theme resolution (Rust; the core)
`classes.rs` learns the H1 vocabulary; `theme.rs` resolves each utility from the
pinned kit's token (measured or derived, by provenance) at render; unknown/absent
token → the platform default value with a diagnostic, never a broken page. Wasm +
helper rebuild ritual; goldens for rendered CSS; scene engine untouched;
`edit-website`/inspector round-trip byte-safe on documents that don't use the new
utilities. Tests: resolution per token incl. mixed measured/derived kits; fallback;
the roundtrip suite.

### Slice G2 — surface tokens for measured bands (ingestion; H3)
The slice-2 measurement mints surface tokens for recurring band colors (threshold +
naming discipline in the brief; the brief agent may then NAME them; the `ladder_gap`
class closes). Fixture: the Stripe navy. (No Rust.)

### Slice G3 — authoring adoption (prompts + skills + recipes)
`create-website`'s class-grammar table gains the geometry utilities; the
design-guidance skill's deployment rules point at them; slice-3 recipes render into
the new utility names 1:1; the author prompt prefers them ("brand geometry comes
from the kit's utilities; raw radius/shadow on a briefed kit is a defect the
reviewer will flag"). Reviewer: raw-geometry-on-briefed-kit becomes an advisory
finding (phase-2 posture per H2).

### Slice G4 — the enforcement walk + phase-2 warning
Live walk: a generation on the approved Stripe kit authored WITH the utilities —
DOM-verify the computed values equal the measured tokens; then flip one kit token
version and confirm the page re-renders geometry from the pin (the color-law parity
proof). Ship the ingest WARNING (H2 phase 2). Close-out: plan header, memory,
walkthrough. Phase 3 (hard lint) stays a registered, founder-gated follow-up.

## 5. Constraints & traps

1. **The rebuild ritual binds every Rust slice** — stale-helper/stale-worker skew is
   the disease this week already diagnosed twice (G7's gitignored asset; the
   stale-worker queue poaching). After any G1 rebuild: restart 8010 AND the fleet
   worker, and check for stray 801x listeners before verifying.
2. **Never break un-briefed/legacy documents** — every phase preserves raw-utility
   validity until the founder flips a kit to strict.
3. **Mixed provenance is normal** — resolution reads per-token provenance; a derived
   fallback renders honestly, never blocks.
4. **The scene engine's `LUMB` codes are precedent, not shared code** — the web
   grammar gets its own LUMW codes; no cross-engine imports.
5. Design tests without the platform `.env`; no `git stash`; single-design-API
   topology (8010) during all verification.

## 6. Out of scope (registered)

Strict mode as DEFAULT (phase-3 flag exists, default-off — product decision);
typography hard-lint (H4); motion/interaction tokens; scene-side changes; the
fleet lease-staleness guard (separate, fleet-owned).
