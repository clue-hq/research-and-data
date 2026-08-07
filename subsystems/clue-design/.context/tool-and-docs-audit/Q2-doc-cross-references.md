# QUESTION 2 — Do our knowledge documents fairly refer to each other? Are they well referenced and connected?

**Scope.** 36 `.md` files under `apps/agent_runtime/knowledge_docs/` (1 `AGENT.md` + 29 `knowledge/**` + 6 `skills/**/SKILL.md`), the loader `apps/agent_runtime/lumen_deepagent/knowledge.py`, and a head-to-head benchmark against Brilliant's 91-file `knowledge/` tree. All adjacency, orphan, and dangling claims below were re-verified against the live files.

---

## 1. Verdict

**Grade: B — (good in the hot path, weak and fraying at the edges).**

**Headline:** The docs that drive the core authoring loop are genuinely well cross-referenced; the docs at the periphery are not. Roughly the top ~60% of the corpus — the **lumen-dsl cluster** (grammar ↔ text ↔ layout ↔ colors ↔ directives ↔ diagnostics) and the **images cluster** (decide ↔ prompts ↔ placement ↔ icons), plus the **blocks catalog** with its clean README index — is bidirectional, internally consistent, and aligned with how the loader pins docs. That part is a clear A.

The remaining ~40% is a **ring of peripheral docs that only `AGENT.md` — or nothing at all — points to.** They are not technically unreachable (the loader retrieves every PRIMARY path by keyword every run and force-pins a mandatory set), but the **agent is never *steered* into them from a related doc.** They surface only on lucky keyword overlap, and when they do they read as redundant-but-unlinked siblings of the live docs (`typography-and-composition` vs `text.md`; `layout-recipes` vs `blocks/patterns.md`).

**The single sharpest defect:** `knowledge/loop/authoring-and-repair.md` — the canonical quality-loop procedure — has **zero inbound references from anywhere, including `AGENT.md`.** `AGENT.md` §3 re-describes the loop inline instead of pointing at the authoritative doc. (Verified: `grep -rln "authoring-and-repair"` over the tree returns nothing.)

Two structural truths frame everything below:
1. **There are no broken doc-to-doc links.** Every in-prose `knowledge/...` pointer resolves to a real file. The connectivity problem is *missing* edges, not *dangling* ones.
2. **We lack the machine-readable dependency graph Brilliant has.** 0 of our docs carry an `assumes:` frontmatter field (verified by grep); our prerequisite knowledge ("this block doc assumes you've loaded the grammar") lives only as English prose the loader cannot act on and an author cannot lint.

So: **fair within the core, unfair at the edges, and missing the one mechanism (declared dependencies) that would make the whole graph self-healing.**

---

## 2. How our docs are wired today

### 2.1 The addressing mechanism (loader reality — important context)

The agent does **not** crawl a hyperlink graph at runtime. `knowledge.py` works in three moves:

- **A fixed candidate list** — `PRIMARY_KNOWLEDGE_PATHS` enumerates all 29 core docs by explicit path (verified lines 16–47). Every PRIMARY doc is a retrieval candidate on *every* run.
- **Keyword ranking** — each candidate is scored against the query, with a `+3 primary_bonus` (line 270), and the top-scoring docs win context slots.
- **Mandatory pins** — `mandatory_task_paths(query)` (line 231) force-includes a task-specific set regardless of score.

This creates **two discovery channels**: (1) the loader's ranked keyword retrieval, and (2) the in-text cross-references the LLM reads and chooses to act on. A doc nothing links to is *not* invisible to the loader — but it **is** invisible to the agent's in-context navigation: the model only re-reads or re-weights what the prose points it to. Question 2 is about channel (2), and that is where the gaps live.

`AGENT.md` §4 is our **central manifest** — a *task → path* table ("Any new design → …", "Any repair → …", "Answering 'can Lumen do X?' → the matching file — never from memory"). This is exactly Brilliant's `all-agents.md` shape and it is a real strength. Our inline pointers also already use the correct **bare-key style** (`for DSL syntax see knowledge/lumen-dsl/grammar + text`) rather than fragile `[x.md](./x.md)` filesystem links.

### 2.2 Reference adjacency (doc → what its prose points to)

```
AGENT.md → (the master map) all skills + lumen-dsl/{grammar,text,colors,layout,directives,diagnostics}
           + design/{foundations,artboard-frame-authoring,layout-recipes,typography-and-composition}
           + design/blocks/{README,patterns,layout,actions,data-display}
           + design-systems/{token-taxonomy,brand-kits,brand-validation,modes,logo-and-assets}
           + assets/asset-placement + export/preview-quality + loop/layout-cluster-repair
           — NOTE: AGENT.md does NOT link loop/authoring-and-repair, and §4 omits a clean
             map-home for layout-recipes / typography-and-composition (they appear only in
             the WRONG/RIGHT example block or a single side row).

lumen-dsl/grammar    → colors, text, layout, directives, diagnostics, images/*, blocks/patterns, design-systems, skills/effects
lumen-dsl/text       → layout, grammar, images/placement, design/foundations, skills/repair-design
lumen-dsl/colors     → skills/effects                         [no link to diagnostics ← gap #10]
lumen-dsl/layout     → loop/layout-cluster-repair
lumen-dsl/directives → diagnostics (implicit), skills/repair-design, skills/tools
lumen-dsl/diagnostics→ loop/layout-cluster-repair, skills/brand-and-tokens, design-systems/brand-validation

design/foundations               → lumen-dsl/grammar, lumen-dsl/text, design/blocks
design/typography-and-composition→ (NOTHING)
design/layout-recipes            → (NOTHING; only an implicit "layout_cluster" phrase)
design/artboard-frame-authoring  → (NOTHING)
design/blocks/README             → patterns, layout, actions, data-display (clean link table)
design/blocks/patterns           → images/decide, images/placement, design/foundations
design/blocks/layout             → (NOTHING; self-contained)
design/blocks/actions            → (NOTHING; self-contained)
design/blocks/data-display       → (NOTHING; internal "Benefit row above" only)

images/decide    → images/prompts, images/placement, images/icons
images/prompts   → images/decide, images/placement
images/placement → (NOTHING outbound; cites .context/p02-validate.py only)
images/icons     → images/decide

design-systems/token-taxonomy → (NOTHING)
design-systems/brand-kits     → token-taxonomy, modes, logo-and-assets, brand-validation   [good hub]
design-systems/brand-validation→ (NOTHING — no skill/token link back)
design-systems/modes          → (NOTHING)
design-systems/logo-and-assets→ (NOTHING — no link to assets/asset-placement)
design-systems/brand-fit-critique→ (NOTHING)

assets/asset-placement → (NOTHING)
export/preview-quality → (NOTHING)
loop/authoring-and-repair → create-design, repair-design, visual-review, lumen-dsl/directives, loop/layout-cluster-repair
loop/layout-cluster-repair→ (NOTHING outbound)

skills/create-design  → lumen-dsl/{grammar,text}, design/{foundations,artboard-frame-authoring},
                        design/blocks/*, images/{decide,prompts,placement},
                        skills/{brand-and-tokens,effects,repair-design}, AGENT.md   [rich fan-out]
skills/repair-design  → lumen-dsl/{diagnostics,directives}, loop/layout-cluster-repair, skills/brand-and-tokens
skills/brand-and-tokens→ design-systems/{logo-and-assets,brand-fit-critique}, token-taxonomy (table, not by-name link)
skills/effects        → lumen-dsl/colors
skills/tools          → assets/asset-placement (implicit), apply_structured_edit refs; no knowledge/ doc links
skills/visual-review  → (NOTHING — pure rubric, links no knowledge doc)   [verified]
```

**Topology in one line:** a tightly woven core (lumen-dsl, images, blocks, create/repair skills) plus a `brand-kits` hub with dead-end leaves, surrounded by a rim of single-parent or zero-parent docs.

### 2.3 Orphans — docs nothing in the prose graph steers the agent into

Genuinely orphaned-in-prose (zero non-`AGENT.md` inbound references), worst first:

| Doc | In-prose inbound | Loader status | Severity |
|-----|------------------|---------------|----------|
| **`loop/authoring-and-repair.md`** | **0** (not even AGENT.md) — verified | PRIMARY-pinned, **not** in `mandatory_task_paths` | **HIGH** — the canonical loop doc, unreachable from AGENT.md and every skill. Loads only if keyword score wins a slot. |
| **`design/typography-and-composition.md`** | AGENT.md only | PRIMARY | MEDIUM — its natural neighbors `text.md` and `foundations.md` never mention it. |
| **`design/layout-recipes.md`** | AGENT.md (example block / side row only; no clean §4 map home) | PRIMARY | MEDIUM — orphaned from `foundations`, `blocks/*`, `artboard-frame-authoring`, which all overlap it. |
| **`export/preview-quality.md`** | AGENT.md only | PRIMARY | MEDIUM — `skills/visual-review` (its consumer) never links it. |

Reachable-but-thin (single parent, no link from the doc that actually *uses* them):

| Doc | In-prose inbound | Severity |
|-----|------------------|----------|
| `assets/asset-placement.md` | AGENT.md + `skills/tools` (implicit) — verified | MEDIUM — `logo-and-assets`, `images/placement`, `images/decide` never point here. |
| `design-systems/brand-fit-critique.md` | `skills/brand-and-tokens` only | LOW — but `skills/visual-review`, the actual critic, doesn't link it. |
| `design-systems/token-taxonomy.md` | AGENT.md + `brand-kits` | LOW — `skills/brand-and-tokens` duplicates the table but doesn't name the doc. |
| `design-systems/modes.md` | AGENT.md + `brand-kits` | LOW — adequately reachable. |
| `design-systems/brand-validation.md` | AGENT.md + `diagnostics` | LOW — reachable, but links *nothing* onward (a sink). |

### 2.4 Dangling references — none broken; three caveats

**No broken doc-to-doc links exist.** Every slug-style `knowledge/...` pointer resolves to a real file. Three non-doc / consistency flags:

1. **`.context/p02-validate.py`** — cited as validator provenance in `blocks/{README,patterns,layout,actions,data-display}` and `images/placement`. This path is **outside** `knowledge_docs/` and is not loadable by the agent. Harmless as provenance prose, but `blocks/README` step 5 reads as an instruction ("re-validate with `.context/p02-validate.py`") pointing at a tool the agent does not have.
2. **`reference_docs/*`** — `SECONDARY_KNOWLEDGE_PATHS` lists the ABM spec + two Brilliant reports, which live outside `knowledge_docs/` and are cross-referenced by no doc. Out of scope; noted for completeness.
3. **AGENT.md §4 ↔ loader drift** — `AGENT.md`'s §4 map does not give `layout-recipes` or `typography-and-composition` a clean "load this" home (they appear in the WRONG/RIGHT example or a single side row), yet both are PRIMARY-pinned in the loader. Not a dangling link — a map/loader inconsistency that leaves two PRIMARY docs without a map home.

---

## 3. Where the connective tissue is missing

Ranked MISSING-BUT-SHOULD cross-references — related-feature doc pairs that do **not** point at each other, each with the linking feature and the exact one-line fix.

| # | Doc A ↔ Doc B | Feature that should link them | One-line fix |
|---|---------------|-------------------------------|--------------|
| **1** | `images/placement` ↔ `assets/asset-placement` | Both place an asset onto a node with fit/crop/aspect/alt; `placement` names `place_asset_in_node`/`place_asset_in_slot` but never links the asset-placement doc, which in turn never mentions the scrim/cover idiom. | Add to `placement`: "For asset-registry rules and the `place_asset_in_node` op contract see `knowledge/assets/asset-placement`." — and link back reciprocally. |
| **2** | `images/decide` & `images/icons` ↔ `design-systems/logo-and-assets` | All route "logo glyph → use a `logo.*`/`asset.*` token, NOT generate_image"; the images cluster says "use a brand `logo.*` token" but never points to the doc defining those roles + background rules. | In the logo rows of `decide` and `icons`: "see `knowledge/design-systems/logo-and-assets` for logo roles + allowed-surface rules." |
| **3** | `skills/visual-review` ↔ `export/preview-quality` | The reviewer judges the rendered PNG/SVG; preview-quality defines what a *valid* artifact is (PNG header, text-node visibility, dimension/aspect checks) — exactly the reviewer's inputs. preview-quality is orphaned; visual-review links nothing. | Add to visual-review Inputs: "The artifact must pass `knowledge/export/preview-quality` validity checks before review." |
| **4** | `skills/visual-review` ↔ `design-systems/brand-fit-critique` | visual-review's "Request & brand" check duplicates brand-fit-critique's rejection list in spirit but never links it; brand-fit-critique is reachable only from the authoring skill, not the critic. | Add to visual-review's brand check: "see `knowledge/design-systems/brand-fit-critique` for the full brand-rejection rubric." |
| **5** | `loop/authoring-and-repair` ↔ `AGENT.md` (+ create-design / repair-design) | THE loop doc links *out* to the skills, but nothing links *in* — AGENT.md §3 describes the loop inline, so the agent never loads the authoritative version. | Add to AGENT.md §3: "Full loop procedure: `knowledge/loop/authoring-and-repair`." |
| **6** | `design/typography-and-composition` ↔ `lumen-dsl/text` + `design/foundations` | All three cover type scale, overflow, hierarchy; the two live ones never mention typography-and-composition, leaving it stranded and partly redundant. | Add "see also `knowledge/design/typography-and-composition` (supported vs future type features)" to `text.md`; or merge/deprecate it. |
| **7** | `design/layout-recipes` ↔ `design/blocks/patterns` + `artboard-frame-authoring` | layout-recipes' per-surface skeletons are the older, looser version of the validator-passed `blocks/patterns`; neither references the other, so the agent may follow un-validated recipes. | In `layout-recipes` header: "Prefer the validator-passed `knowledge/design/blocks/patterns` for production; these are reference skeletons." |
| **8** | `design-systems/brand-validation` ↔ `skills/brand-and-tokens` + `lumen-dsl/diagnostics` | brand-validation defines the LUMB repair policy; diagnostics links *to* it, but it links *to nothing* (no "repair via tokens, see skills/brand-and-tokens"). | Add to brand-validation Repair Policy: "see `skills/brand-and-tokens` for the token-by-token fix table." |
| **9** | `design-systems/token-taxonomy` ↔ `skills/brand-and-tokens` | The skill reproduces the taxonomy table but never names the doc; token-taxonomy links nothing onward (to brand-kits/modes). | Add to `token-taxonomy`: "For authoring/repair procedure see `skills/brand-and-tokens`; for kit status/modes see `brand-kits`/`modes`." |
| **10** | `lumen-dsl/colors` ↔ `lumen-dsl/diagnostics` | colors enumerates LUMD0218/0219/0239/0240 color codes but never links the diagnostic map; the reverse path exists implicitly via grammar only. | Add a "full code map: `knowledge/lumen-dsl/diagnostics`" footer to `colors.md`. |

---

## 4. What Brilliant does that we don't

Benchmark root: Brilliant's `.claude-prod/` — 99 `.md` files, 91 under `knowledge/`. Brilliant runs **three layered mechanisms** and, crucially, uses them in **two registers** by doc type.

| Layer | What it is | Our status |
|-------|-----------|-----------|
| **1. Central task→key manifest** | `all-agents.md` maps *tasks → flat dotted keys* with an explicit `### Available keys` enumeration. The agent loads by key via `get_knowledge(keys:[...])`, never by crawling links. | **We have this.** `AGENT.md` §4 is the same shape. Strength to keep. |
| **2. Machine-readable `assumes:` frontmatter** | A YAML field declaring prerequisite keys. `get_knowledge` *resolves dependencies off it* — loading a leaf transitively pulls its base (`hosted.md` lines 16/38). Present in **65 of 91** generative docs. | **We have 0.** This is the single biggest thing they do that we don't. |
| **3. `dsl:` reverse index** | 26 files list the DSL keywords they own (`dsl: [line, len, angle, …]`), so an unknown token routes to its home doc. | **We have 0.** |

**The split-register insight (worth copying exactly):**
- **Generative/authoring docs** (blueprint, design, effects, charts, …) carry `assumes:` + terse **bare-key** prose pointers (`see blueprint/lines`) and **zero** markdown links / "See also" footers. Cross-reference is machine-readable, not prose-chained.
- **Reference/Q&A docs** (`reference/*`) use richer `[file.md](./file.md)` links and "See also" footers — and *those links are partly broken* (`[knowledge/SKILL.md](./SKILL.md)` points at a nonexistent file; wrong-case/wrong-path targets abound). This is the **strongest evidence that key-addressing, not link-following, is the real navigation system** — the path-links rotted precisely because nothing reads them.

**Transferable lessons:**
1. **Add `assumes:` to every generative doc** and have the loader resolve it transitively. This turns "the agent forgot to load grammar before components" from a silent failure into an automatic include — directly fixing our orphan problem at the loader level, not just the prose level.
2. **Add a `keywords:`/`dsl:` reverse-index field** per doc so unknown tokens route home.
3. **Keep the two registers separate.** Our generative docs should stay frontmatter + bare-key pointers; never let prose link-chains creep in (they cost tokens and rot, as their `reference/` proves).
4. **Reference by loadable key, never by filesystem path.** Our `knowledge/lumen-dsl/grammar` style is already correct — enforce it, ban `[x.md](./x.md)`.
5. **Adopt the `redirect:` tombstone pattern** (their `blueprint/shaders/holo.md` is a 1-line `redirect: blueprint/shaders/irid`) so merged/renamed docs forward instead of dangling — directly relevant to deprecating `typography-and-composition` / `layout-recipes`.
6. **Lint the graph in CI.** Once `assumes:` exists, verify every `assumes:` key and every bare-key prose pointer resolves to a real manifest key — catching exactly the dangling class Brilliant's own `reference/` fell into.

---

## 5. Fix plan (ordered, highest-impact first)

### Tier 0 — make the canonical docs reachable (1 PR, ~30 min)
1. **Link `loop/authoring-and-repair` from `AGENT.md` §3** ("Full loop procedure: `knowledge/loop/authoring-and-repair`") and from `skills/tools` (loop order). Fixes the single sharpest defect.
2. **Give `layout-recipes` and `typography-and-composition` a clean §4 map home** in `AGENT.md` (resolve the map↔loader drift), or deprecate them (Tier 3).

### Tier 1 — wire the critic and the asset/imagery boundary (the highest-leverage prose edges)
3. **Critic → its rubrics:** add to `skills/visual-review` links to `export/preview-quality` (validity gate) and `design-systems/brand-fit-critique` (brand-rejection rubric). [missing-ref #3, #4]
4. **Asset/imagery boundary:** reciprocally link `images/placement` ↔ `assets/asset-placement`, and link `images/decide` + `images/icons` → `design-systems/logo-and-assets`. [#1, #2]

### Tier 2 — close the design-systems loop (kill the dead-end leaves)
5. Add reciprocal "see also" pointers so `token-taxonomy` and `brand-validation` point back to `skills/brand-and-tokens`; have `brand-validation` link `diagnostics` and the token fix table. [#8, #9]
6. Add the `colors → diagnostics` "full code map" footer. [#10]

### Tier 3 — resolve the redundant-stranded design docs
7. Cross-link or **deprecate** `typography-and-composition` against `text.md`/`foundations.md` and `layout-recipes` against `blocks/patterns.md`, marking the validator-passed doc as the production source. [#6, #7] Use a `redirect:` tombstone if deprecating.

### Tier 4 — adopt Brilliant's machinery (the durable, structural fix)
8. **Add `assumes:` frontmatter** to every generative knowledge doc (lumen-dsl/*, design/*, design-systems/*, images/*) and **extend `knowledge.py` to resolve it transitively** — promote prose prerequisites into a loader-walkable dependency graph. This is the structural cure for the entire orphan ring.
9. **Add `keywords:`/`dsl:` reverse-index frontmatter** for token→doc routing.
10. **Add a `Related` footer convention** (bare-key only) to each generative doc, derived from `assumes:` so it cannot drift.
11. **Add a CI graph linter** asserting (a) no `[x.md](./x.md)` links in generative docs, (b) every `assumes:` key + every bare-key prose pointer resolves to a PRIMARY path, (c) every PRIMARY doc has at least one inbound prose reference (would have caught `authoring-and-repair` automatically). Adopt `redirect:` tombstones for renames.

**Net effect:** Tiers 0–2 raise the grade from **B−** to **A−** by closing every orphan that has a natural neighbor. Tier 4 makes the graph self-healing and lint-enforced — the difference between "well-connected today" and "stays well-connected."

---

### Appendix — verified facts
- `grep -rln "authoring-and-repair"` over `knowledge_docs/` → **no matches** (confirms zero inbound, including AGENT.md).
- `grep -rl "assumes:"` → **0 files** (no machine-readable dependency graph).
- `skills/visual-review/SKILL.md` contains **no** `knowledge/` pointer (confirms the critic links nothing).
- `asset-placement` inbound = `AGENT.md` + `skills/tools` (confirms it is reachable-but-thin, not fully orphaned).
- Loader: `PRIMARY_KNOWLEDGE_PATHS` lists all 29 core docs (knowledge.py:16–47); `+3 primary_bonus` at line 270; `mandatory_task_paths` at line 231 — confirming every PRIMARY doc is a keyword candidate every run but only the pinned set is forced.

**Key paths:** all docs under `/Users/aryankeshri/conductor/workspaces/clue-design/havana/apps/agent_runtime/knowledge_docs/`; loader `/Users/aryankeshri/conductor/workspaces/clue-design/havana/apps/agent_runtime/lumen_deepagent/knowledge.py`; manifest to extend `…/knowledge_docs/AGENT.md` §4. Brilliant benchmark: `…/brilliant-design/package/Contents/Resources/.claude-prod/all-agents.md`, `…/hosted.md`, `…/knowledge/blueprint/components.md` (`assumes:` exemplar), `…/knowledge/blueprint/shaders/holo.md` (`redirect:` exemplar).

---

## Addendum — verified critic corrections (fold these in)

A completeness critic re-checked this audit against the live files. The verdict (**B−**, fair in the core / weak at the edges) and every missing-pair stand. Two precision fixes:

1. **Our corpus is NOT uniformly bare-key.** `knowledge/design/blocks/README.md` (L17–20) uses exactly the `[patterns.md](patterns.md)` relative-markdown style this report recommends banning — the very table praised as a "clean link table." So the "ours is already correct" claim has a real exception, and the **CI-linter recommendation (Tier 4 #11a) has a concrete existing target**: either convert those 4 links to bare-key, or formally allow them as the one reference-register table. The linter is more load-bearing than the body implied.
2. **`.context/p02-validate.py` exists** (≈2.2 KB, referenced in **6** docs: `blocks/{README,layout,actions,patterns,data-display}` + `images/placement`), so it is not a phantom path. The substantive defect is unchanged: it lives **outside** the loadable `knowledge_docs/` tree, so `blocks/README` step 5 instructs the agent to run a validator it cannot reach from context.
3. **Confirmed (not padding):** `skills/visual-review/SKILL.md` contains zero `preview-quality` / `brand-fit-critique` / `export` references — so missing-pairs **#3 and #4 are real and high-value**. `brand-fit-critique` inbound = `skills/brand-and-tokens` only (LOW severity confirmed).

---

## Implementation status — Tier 0–1 SHIPPED, the Brilliant way (2026-06-26, branch `add-image-model-to-design-tool`)

Rather than fragile prose "see also" lines, Tier 0–1 was wired using **Brilliant's actual machinery** — `assumes:` frontmatter resolved transitively by the loader (Brilliant's `get_knowledge` dependency resolution), the bare-key task→keys manifest (`AGENT.md` = `all-agents.md`), and bare-key prose only for lateral/SKILL edges. This makes the cross-links machine-resolvable and lint-checkable instead of rot-prone.

- **Robustness engine (`knowledge.py`):** new `parse_frontmatter`/`assumes_keys`/`assumes_path`; `read_task_knowledge` now force-pulls a selected doc's `assumes:` prerequisites transitively (before the score-ranked fill). Docs delivered un-stripped (preserves `excerpt == on_disk`).
- **`assumes:` edges (machine-resolved):** `images/placement → images/decide, assets/asset-placement`; `images/prompts → images/decide`; `images/icons → images/decide`. [missing-ref #1]
- **Bare-key prose (lateral/SKILL):** `assets/asset-placement → images/placement + logo-and-assets` (reciprocal); `images/decide` & `images/icons` logo rows → `logo-and-assets` [#2]; `skills/visual-review` → `export/preview-quality` (validity gate) [#3] + `design-systems/brand-fit-critique` (brand rubric) [#4].
- **Manifest (`AGENT.md`):** §3 → `knowledge/loop/authoring-and-repair` (fixes the sharpest orphan [#5]); §4 "Reviewing a preview" row → adds `brand-fit-critique`; new clean home row for `layout-recipes` (framed as reference skeletons vs the production `blocks/patterns`). `skills/tools` loop-order → loop doc.
- **Guard tests (scoped Tier-4 linter):** `test_assumes_frontmatter_resolves_transitively`, `test_knowledge_assumes_keys_resolve_to_real_primary_docs`, `test_parse_frontmatter_is_a_noop_without_a_block`. Verified: 36 bare-key pointers across the 8 edited docs, **0 dangling**. **Full agent suite: 97 passed, 2 skipped.**

Still Tier 3/4 (not in this bundle): deprecate/redirect `typography-and-composition` vs `text.md` and `layout-recipes` vs `blocks/patterns` (#6/#7) via `redirect:` tombstones; roll `assumes:`/`dsl:` frontmatter out to the **whole** corpus + a CI graph linter.
