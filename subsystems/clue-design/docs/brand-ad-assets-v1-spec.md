# Brand Ad Assets v1 — from proof of concept to demo-able product

**Status: W1 APPROVED FOR EXECUTION (founder, 2026-08-26) — "proceed with
the first wave as per your plan." §8 open items remain open: D1's backstop
default stands unless struck; W1.9 stays deferred pending a ruling; the
Adyntel commercial step is the founder's.** W2–W5 remain gated on further
review. Skill *content* additionally requires its own founder review before
authoring (ruling D6 below).

**AMENDMENT — founder rulings, 2026-08-26 (ratified in chat). These OVERRIDE
this document where they conflict; the W2/W3/W4 rows below were edited to
match.**

- **D8 — the ad-DNA card is FREE PROSE, not a taxonomy.** The structured
  five-field per-visual-system shape written into §4.2 (layout skeleton /
  ground treatment / accent spend / logo placement / type relationships) is
  **rejected as over-specification**. The vision pass describes the harvested
  ads **in its own words**, with a *soft* coverage nudge (layout, colour
  behaviour, imagery style) that is explicitly a suggestion and never a schema
  requirement. The only structure that survives is the minimal machine link
  reference selection needs: **which described style groups map to which
  `creative_id`s**. Versioning, provenance and the bounded length are
  unchanged. Card `schema_version` 1 → 2; the column is `jsonb`, so no
  migration.
- **D9 — the composition corpus is DORMANT.** W4 does **not** reference it,
  load it, or point the agent at it in any prompt or context. The corpus docs
  stay where they are, untouched, until a later ruling wakes them.
- **D5 and D1 restated for W4:** no approval gates and no mechanical guards on
  the agent; budgets stay guidance over a distant backstop.

---

## 1. Goal

Turn the proven reference-conditioned ad pipeline into a workable, demo-able
product feature integrated with the scene design deepagent: a client onboards,
the platform harvests their published LinkedIn ads, distills their ad DNA,
pre-generates brand-coherent imagery, and every subsequent ad the design
deepagent produces is conditioned on the brand's own proven creative — with
the image model supplying atmosphere and illustration, and the engine
supplying structure, typography, and tokens.

This spec covers the backend feature and deepagent integration only. Product
UI for ad assets is explicitly deferred (ruling D4).

## 2. Evidence base (frozen POC baselines — do not re-derive)

Five proofs, 2026-08-25/26, all on branch `integration/frontend-design-part-iv-v4`:

| POC | What it proved | Key artifact |
|---|---|---|
| Stripe references (legacy loop) | Reference steering: gradient artboard + rounded card + shadow, matching Stripe's system | `.deepagent-workspace/run_c10c81d793e34413a83397042b2bf72c` |
| Cursor references (fast loop) | Selective imitation: dark poster chassis chosen, calculator UI refused, token-honest color resolution; fidelity 2/3 | `run_b206d2b294a343cfa2d6df47f1af6b52`; `.context/ref-ads-pilot-cursor-report.md` |
| Apollo + image model | Layer-stack division of labor: generated holographic wash ground + cream card + CTA pill, produced with ZERO brand kit; fidelity 2 | `run_892dcf6b9d1a476e8a81158064603e85`; `.context/ref-ads-pilot-apollo-report.md` |
| Budget/reasoning A/B | medium reasoning halves call latency; 900s vs 600s turned fidelity 1 → 2 (run reacted to its own critique) | Apollo report §runs |
| Ramp fetch | Adyntel: domain → provenanced creatives; 34 uniques / 2 credits; URLs expire → bytes custodied at fetch | `.context/ramp-ads/` |

Failure ledger from the POCs = enumerated requirements (§5 W1).

## 3. Decision register (founder rulings, 2026-08-26)

- **D1 — budgets are guidance, not gates.** Reasoning effort: medium. Time
  target ~900s and iteration targets are communicated to the agent at the
  PROMPT level ("you cannot take more than…"); there is **no hard cut** at the
  target. A distant safety backstop (~2× target) exists solely as a circuit
  breaker for hung/runaway runs, with graceful finalize of checkpointed work
  — the agent never encounters it in normal operation. *(Backstop is the
  recommended default; founder may strike it at ratification.)*
- **D2 — own ads only by default.** Competitor-ad conditioning is an explicit
  per-client opt-in, never a default.
- **D3 — Adyntel is the v1 fetch vendor**, wired behind the standard resolver
  seam so the provider is swappable. Credentials live in proper secrets
  handling (env), never in the repo.
- **D4 — no product UI in v1.** Ad assets live in the backend, accessible to
  the design deepagent. Where they surface in the product is a later ruling.
- **D5 — no approval gates in v1.** Harvested references, the ad-DNA card,
  and pre-generated assets are born active and immediately usable. No
  mechanical/deterministic guards blocking the deepagent. A client-facing
  review surface is deferred to the D4 UI ruling, as product value not as a
  gate.
- **D6 — skill content is founder-reviewed substance.** For every skill:
  outline discussed in chat → full draft text presented in chat → founder
  sign-off → only then is an author agent dispatched. Plain,
  one-idea-per-sentence language throughout (standing ruling).
- **D7 — skill 2 scope.** Not "background generation" — a full
  **generative-imagery** skill: strong prompting for ANY generated need
  (transparent spot illustrations, abstract backgrounds, brand-themed
  illustrations, specific design elements), including reference-image
  conditioning of the generation call and a dedicated brand-coherent
  prompting section. Backgrounds are one section of it.

## 4. Architecture — the Brand Ad Assets lane

**[SUPERSEDED 2026-10-30 — reference ads, `docs/superpowers/specs/2026-10-30-design-reference-ads-design.md`
(repo root): style groups are retired (the card is prose only; `style_groups` stays in the
stored payload, always empty), nothing is auto-attached, the agent gets the brand's whole ad
list in `ad-assets.md` and opens the ones it wants, and pre-generation makes one background
from each of up to four different ads.]**

A brand-kit-adjacent, versioned lane populated at onboarding, three artifact
kinds:

1. **Harvested reference creatives.** Fetched by the ad-library resolver
   (Adyntel LinkedIn endpoint; input = client domain), filtered to static
   company ads (drop video/carousel/document and personal thought-leader
   promotions), deduped by creative URL, **bytes downloaded at fetch time**
   (CDN URLs expire) into durable asset storage, provenance stamped (ad id,
   library detail link, fetch time, advertiser page id).
2. **The ad-DNA card.** A bounded, versioned artifact distilled ONCE per
   harvest by a vision pass over the creatives. **[AMENDED by D8, 2026-08-26 —
   this row originally specified a five-field per-visual-system taxonomy
   (layout skeleton, ground treatment, accent spend, logo placement, type
   relationships). That taxonomy is REJECTED.]** The card is now **free
   prose** — the ads described in the model's own plain words, under a soft
   coverage nudge — plus **style groups** (`{name, creative_ids}`), the one
   machine link turn-time reference selection needs. Pushed into every ad
   turn's opening context as advisory text; never re-derived per run.
3. **Pre-generated imagery.** Per style group, 2–3 assets generated offline
   against the references (abstract grounds, transparent spot illustrations,
   textures), stored as **brand-kit assets** so the scene turn can place them
   (see W1.1). Runtime generation remains available for bespoke needs.

Runtime composition (no new agent roles — ruling from the fast-loop era
stands): the turn's frame payload carries the ad-DNA card's prose as advisory
text; the platform auto-attaches the ≤4 most relevant harvested references
(cap-4 ruling stands); the two skills govern method. **[AMENDED by D8: the
concept plan gains no typed visual-system slot — the planning obligation is
carried by the `reference-conditioned-ads` skill in words, which is what a
prose card can honestly feed.]**

## 5. Workstreams

### W1 — fidelity & plumbing bug wave (land first; parallel; unflagged — they are bugs)

| # | Item | Symptom / evidence |
|---|---|---|
| 1 | Library→scene-turn asset channel | `workspace_asset_library_manifest()` only wired into website turns; scene turns can view/place only kit assets + per-turn references. Pre-generated backgrounds were unplaceable (Apollo POC). Fix: expose the library manifest to scene turns AND/OR store pre-generated imagery as kit assets. |
| 2 | Font byte custody in website ingestion | Fonts scraped by URL with `asset_id: null`; nothing ever paints (`LUMS0100` → Inter fallback, every run). Top visible-quality bug. |
| 3 | Tailwind color-parse crash | Bare `float()` in `capture/parse.py` dies on `rgb(15 23 42 / var(--tw-text-opacity))`; kills whole ingestion (apollo.io, 4/4 URLs). Any Tailwind client site is blocked. |
| 4 | `IMAGE_MODEL_ID` broken in `.env` | `openai/gpt-image-2` 404s on the chat-completions image modality; working model verified: `openai/gpt-5.4-image-2`. **[Correction, W1.4 execution 2026-08-26:** this row originally read "does not exist on OpenRouter". It exists — OpenRouter runs two endpoints with disjoint catalogues, and `gpt-image-2` is served only by the dedicated Image API (`/api/v1/images`), not by the chat-completions path this provider uses. The POC's catalogue query hit `/api/v1/models` (chat), which is why it found no match. Same for `openai/gpt-image-1{,-mini}`. Consequence for W1.7(b): the Image API also exposes `aspect_ratio`, `background` and `input_references` as first-class parameters — a future provider-seam swap worth considering.**] |
| 5 | `reference_fidelity` typed field | Score sometimes lands only in `acceptance_notes` prose with the typed field null (Cursor runs); gate + metrics need the typed field always stamped. |
| 6 | Logo policy vocabulary | `LUMB0810`: reference-driven placement (reversed logo on `$surface.inverse`) not expressible in `allowed_backgrounds`; agent had to deliberately violate. Add the vocabulary; keep it advisory (D5). |
| 7 | Generation robustness | One retry on `image_model.no_image` text-only responses; honor `aspect_ratio` or document the constraint; never block the design on failed generation — fall back to flat token ground. |
| 8 | Budget/reasoning config defaults | Wire D1: medium reasoning; prompt-level time/iteration guidance; hard wall becomes the distant backstop. (Knobs exist: `LUMEN_AGENT_FAST_LOOP_WALL_CLOCK_S` etc.) |
| 9 | Ingestion depth knob (small, optional) | No cap parameter exists on `IngestWebsiteRequest` (founder asked for one during POC); decide expose-or-not once, record it. |

### W2 — the substrate (flag-gated)

**[Status: BUILT. Amended by D8 — the card the distiller writes is the prose
card, `schema_version` 2; pre-generation prompts are anchored in that prose
plus the style group's name. The durable `visual_system` link column keeps its
W2 name and now carries the group name — renaming it would be a migration that
buys nothing.]**

Schema for the ad-assets lane (creatives + provenance, ad-DNA card versions,
pre-generated asset links); the Adyntel resolver behind the resolver seam
(request/response per their LinkedIn endpoint; pagination via
`continuation_token`; never `all_ads`; 1 page ≈ 25 ads ≈ 1 credit); the
onboarding job: harvest → filter/dedupe → custody → distill → pre-generate.
The POC scripts in `.context/ramp-ads/` are the harvest reference
implementation.

### W3 — skills + corpus (gated on D6 founder review, per skill)

- **`reference-conditioned-ads`** (workflow) — outline APPROVED 2026-08-26:
  what/why, why-not (freestyle, pixel-copy), the layer-stack model, selective
  imitation rules (system vs content; refuse non-reproducible; token-honest
  color; reference-vs-kit conflict rule), planning obligations
  (visual-system slot), generate-vs-draw, reference_fidelity criteria.
- **`generative-imagery`** (craft; scope per D7) — outline to be presented:
  strong-prompting fundamentals; asset types (transparent spot illustration,
  abstract ground, brand-themed illustration, design element, texture, prop);
  **reference-conditioning the generation call** (passing reference images);
  **brand-coherent prompting** (anchor prompts in the kit's actual palette/
  mood); placement mechanics (cover ground vs positioned spot node; scrim
  rule); failure handling per W1.7.
- **Composition corpus**: validated snippets (card-on-ground, pill chip,
  framed plate, divider) + 2–3 skeletons (unequal-weight comparison panel,
  card-on-washed-ground). Each snippet shown to the founder before entering
  the corpus. **[Status per D9, 2026-08-26: BUILT AND DORMANT. It exists on
  disk and nothing loads it. W4 was built without it and must not reference
  it. Waking it is a later ruling.]**

### W4 — runtime composition

**[AUTO-ATTACH AND SELECTION SUPERSEDED 2026-10-30 — reference ads, `docs/superpowers/specs/2026-10-30-design-reference-ads-design.md`
(repo root): style groups are retired (the card is prose only; `style_groups` stays in the
stored payload, always empty), nothing is auto-attached, the agent gets the brand's whole ad
list in `ad-assets.md` and opens the ones it wants, and pre-generation makes one background
from each of up to four different ads.]**

**[Status: BUILT, 2026-08-26, flag-gated by the same `LUMEN_BRAND_AD_ASSETS`.
Flag off = byte-identical, proven. Built WITHOUT the composition corpus
(D9).]**

The card's prose into the frame payload as advisory text next to the brand
card; reference auto-selection (≤4) at turn composition; scene-turn
consumption of the lane (rides W1.1); D1 budget prompting.

As built, in one hook: `run_agent_turn_preview` reads the lane once and, when
the human attached nothing, attaches up to four harvested creatives through
the same by-value manifest the manual path uses. Both entry paths pass through
that one line — the standalone `POST /agent/turns` route (which resolves
manual references in its handler) and the platform design-leg envelope (which
carries no manifest key at all and therefore resolves in-worker). **Manual
references always win**; auto-attach never overrides or tops up a human's
attachments, and an unresolvable auto-attachment costs the turn its references
rather than the turn.

Selection v1 is deliberately the simplest honest mechanism: if the card names
style groups, ONE cheap bounded text call matches the brief against the group
NAMES (skipped outright when there is only one group); everything else — no
card, no groups, a failed call, an invented name, a stale group — falls back
deterministically to the most recently harvested creatives.

Deferred from this workstream: the concept-plan visual-system slot (the
planning obligation lives in the `reference-conditioned-ads` skill, which W3
shipped; no typed slot was added, and none is needed for W5).

### W5 — acceptance (the gate)

Same three-brand benchmark: Cursor, Apollo, Ramp. One turn each through the
REAL integrated path (onboarding-populated lane, auto-attached references,
no hand-fed anything), judged side-by-side against (a) the frozen POC frames
and (b) the brands' real published ads. Pass = each output is a recognizable
member of its brand's visual system, reference_fidelity ≥ 2 typed, fonts
paint, logo places, and the run completes without touching the backstop.
Plus one demo script: onboard a fresh brand end-to-end and generate an ad,
live.

## 6. Sequencing

W1 first (parallel worktrees; W1.1–W1.4 gate everything downstream). W2 ∥ W3
next (W3 pacing set by D6 reviews). W4 after W1.1 + W2. W5 last. Working
method unchanged: Opus agents in verified worktrees, base-state attestation,
diff review, red-case proofs, local commits only, nothing pushed.

## 7. Out of scope (v1)

Product UI (D4); Meta/Google fetchers (seam-ready, not built); the variants
track; competitor opt-in flow mechanics (D2 records the default only);
carousel/video creatives; client-facing review surfaces (D5).

## 8. Open items at ratification

1. D1 backstop: keep the ~2× circuit breaker, or pure-advisory only?
2. W1.9: expose an ingestion depth knob, or drop the ask?
3. Adyntel account/credit plan for production use (D3 records the vendor
   choice; the commercial step is the founder's).
