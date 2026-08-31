# 2026-08-24 — engine fix: author text fill beats the type role's baked color

Base: `8729143a6` ("merge color-craft wave"), branch `integration/frontend-design-part-iv-v4`.
Scope: `crates/lumen-core/src/brand.rs` (+ tests in `crates/lumen-core/tests/brand_tokens.rs`).
Single-file surgical change. No threshold changes, no kit changes, no Python changes.

## The bug

In `resolve_node`'s text-style block (`brand.rs`, was ~line 3593), when a text node's
style role resolved and the role carried a baked `color`, the resolved role color
**unconditionally overwrote the node's first fill**:

```rust
if let Some(fill) = node.fills.first_mut() {
    fill.paint = paint;          // <-- clobbers whatever the author wrote
} else {
    node.fills.push(Fill { id: format!("{}_text_fill", node.id), paint });
}
```

So an author who wrote `fill($text.inverse)` (white) alongside `style($type.display)`
(which bakes `color: text.primary`) silently rendered the role's dark color instead.
The P1.1 contrast correction did not rescue it, because on a mid-tone branded ground
the dark-on-brand pair *clears* the guard's lenient 3.0 floor — so the correction had
no reason to fire and the wrong color stood.

### Live evidence (read-only)

`run_bcdcf3e484fd48b7805c8eb561a64854`, iterations 001-004:

- 001 `dsl.lumen` authored `headline text ... style($type.display) ... fill($text.inverse)`
  on an `artboard ... fill($surface.brand)` ground. Same for `eyebrow` and `body`.
- 002 `preview.svg` renders that node as
  `data-lumen-node-id="headline" ... fill="#000000" data-lumen-fill-id="paint_headline_fill_1"`.
  Note the fill **id**: it is the DSL compiler's author-fill id, carrying the role's
  black. That is the clobber, proven at raster.
- 003 the authoring agent gave up on the token and wrote `fill(#FFFFFF)` literally —
  which the old code clobbered too (the clobber never inspected the paint).
- 004 went back to `fill($text.inverse)`. The agent never found a way to win.

## Scout findings — how author fills are distinguishable from role fills

This was the crux. The honest signal is the **fill id**, and it is reliable:

1. **`node.fills` is populated only by an explicit authored `fill(...)`.** Both DSL
   fill-construction sites (`dsl.rs` `DslProperty::Fill`, in the create path ~line 4904
   and the modify/patch path ~line 3134) push a `Fill` only when the author wrote the
   property; the modify path additionally only sets `patch.fills` when the vector is
   non-empty. There is no default/implicit fill for text nodes. **A text node with no
   authored fill therefore has `fills == []` at resolution time** — which is exactly
   the `else` branch the P1.1 work was built around.
2. **Author fill ids are minted by the compiler as `paint_{node_id}_fill_{n}`** (or
   supplied by the caller/scene author).
3. **The only fill this block ever synthesizes is `{node_id}_text_fill`.** That literal
   appears exactly once in the entire source tree (`brand.rs`); every other hit in the
   repo is inside gitignored run artifacts.
4. **Node fills are already resolved before the text block runs.** `resolve_node` walks
   `for fill in &mut node.fills { self.resolve_fill(...) }` at its top, so an author's
   `fill($text.inverse)` is *already* a `Paint::Solid` with the right color by the time
   the role block executes. The fix does not need a new resolution path — it only needs
   to stop overwriting the one that already ran.
5. **The block runs at most once per node per resolution.** `resolve_text_style` returns
   `None` unless `style_token` is set (or `font_family` still looks like a token ref),
   and the block clears `style_token`. So there is no "resolve twice and the role fill
   looks like an author fill" hazard on a straight re-resolve.

Because of (5) the id check is belt-and-braces rather than load-bearing today, but it is
kept deliberately: it keeps the role able to update **its own** synthesized fill in place
if a role is ever rebound over an already-resolved scene, instead of freezing the previous
role's color. Treating "any fill present" as author-authored would have introduced that
regression.

## The precedence rule implemented

> A style role's baked color is a **default** for text that carries no color of its own.
> An author's explicit fill — token or literal — **wins**, and resolves through the
> ordinary node-fill path that already ran.

Mechanically: before applying the role color, compute

```rust
let role_owned_fill_id = PaintId::from(format!("{}_text_fill", node.id.as_str()));
let has_author_fill = node.fills.first().is_some_and(|f| f.id != role_owned_fill_id);
```

and gate the whole existing color block on `!has_author_fill`
(`style.color.filter(|_| !has_author_fill)`). Everything inside the block — including
the P1.1 `contrast_corrected_text_color` call and the 3.0 floor — is **unchanged**.

## Existing pins: what was checked, what changed

**Nothing was changed. No existing test pinned the clobber of an explicit author fill.**
Specifically checked:

- `brand_tokens.rs::text_color_is_corrected_for_surface_contrast` — the P1.1 pin. Its
  headline has **no** fills, so it is the preserved `else` path. Still green, untouched.
- `brand_tokens.rs::resolver_materializes_scene_tokens_without_renderer_semantics` — the
  one test with a text node carrying *both* `style_token: type.headline` and an explicit
  `fills[0]` (`paint_headline_existing`, token `text.primary`). It asserts the fill id
  survives and the paint is `Solid{Hex}` — it never asserts the *value*. Green before and
  after (before: role color; after: the author's own `text.primary`, same family).
- `brand_tokens.rs::font_size_step_token_overrides_role_default_size` — no fills; asserts
  size/weight only. Unaffected.
- `brand_tokens.rs::scene_brand_governance_flags_insufficient_text_contrast` — uses
  `validate_scene_brand_governance`, not `resolve_scene_tokens`. Unaffected.
- `text_token_honesty.rs` (the whole "raw fills edits detach the type role" family) —
  these pin that an **editor** recolor via `apply_operation` clears `style_token`. That
  is the *editor-side workaround* for this very bug: it existed because the role would
  otherwise re-resolve over the user's color. The rule is still correct and all 19 tests
  stay green; it is now belt-and-braces rather than the only defense. Deliberately left
  in place — narrowing it is a separate, editor-owned decision.

## Tests added (all in `brand_tokens.rs`)

A shared helper `resolved_text_fill(style_token, author_fill, surface_hex) -> (PaintId, hex)`
plus a `BRAND_GROUND` constant (`#7C3AED`), chosen so the role's `text.primary` (`#111827`)
**clears** the 3.0 floor (~3.1:1) while the author's white is markedly better (~5.7:1) —
i.e. the exact shape where the correction has no reason to fire.

1. `author_token_fill_beats_the_type_role_color` — `fill($text.inverse)` + `type.display`
   on `BRAND_GROUND` resolves to `#FFFFFF`, in the author's own fill entry. **RED at base.**
2. `author_literal_hex_fill_beats_the_type_role_color` — same for a literal `#FFFFFF`.
   **RED at base.**
3. `text_with_no_author_fill_still_takes_the_role_color_and_p1_1_correction` — no author
   fill: role color lands in the role-owned `headline_text_fill` entry; `#111827` on white
   and on `BRAND_GROUND` (clears the floor, stands), `#FFFFFF` on `#0B1220` (P1.1 fires).
   **GREEN at base and after** — this is the preservation pin.
4. `authored_dsl_hero_keeps_its_inverse_text_on_the_brand_ground` — run-2's exact shape
   end-to-end through `compile_dsl_into_scene`: branded artboard, three text children each
   naming a role *and* `fill($text.inverse)`. All three must be white. **RED at base**
   (eyebrow came back `#0891B2`, the `type.eyebrow` role's `text.accent`).

Red-proof was run explicitly: with `brand.rs` stashed, 1/2/4 FAIL and 3 passes.

### Scout correction worth keeping

The first draft of these tests used `#155E75` (the kit's `surface.brand`) as the ground.
Two tests passed at base — because on that darker ground P1.1 *was* already flipping the
role's dark color to white, accidentally producing the right answer. A test that is green
for the wrong reason is worse than no test. Also: `text.primary` in
`platform_default_brand_kit()` is `#111827`, **not** the `#0F172A` in `brand.rs`'s
`ensure_color` fallback table (`ensure_color` only inserts when the token is absent) —
worth remembering before asserting hardcoded token values in engine tests.

## Gates

| Gate | Result |
|---|---|
| `cargo test --workspace` (per-target, `visual_regression` excluded) | PASS — all 20 other lumen-core targets + lib (25), all other crates |
| `cargo build -p lumen-api-helper --release` | PASS |
| `bash scripts/build_wasm_core.sh` | PASS — 2654410 raw / 817767 gzip, within 3MB budget |
| `node scripts/verify_handshake.mjs` | **HANDSHAKE OK** — both sides `4bf63781be19` |
| `pytest apps/agent_runtime/tests` | PASS (exit 0, 3 skips) |
| focused `apps/api` subset | see below |

### Pre-existing failures, NOT caused by this change (verified at base)

- `lumen-core --test visual_regression` — **does not compile**: `include_bytes!` of
  `fixtures/visual_regression/baselines/*.png`, which do not exist. Documented.
- `lumen-skia --test raster_golden` — 4 failures, all `missing golden ...; run with
  UPDATE_SKIA_GOLDENS=1`. **Same class**, and *not* previously documented alongside
  `visual_regression`. `git ls-files crates/lumen-skia/tests/goldens/` returns **zero**
  tracked files and the directory does not exist; the paths are not gitignored either.
  Confirmed identical failure with the fix stashed. Worth adding to the standing
  "known pre-existing engine-gate failures" note so the next wave does not re-triage it.
- `cargo fmt --all -- --check` is dirty repo-wide **at base** (~4710 diff lines across
  ~70 files, rustfmt version skew) so it is not a usable gate. Handled by diffing the
  fmt output before/after: my hunks add **zero** new complaints.

### Environment notes for the next agent

- This worktree was provisioned on a **stale base** (`5ea7a879`, the PR-#42 merge). Tree
  was clean, so `git reset --hard 8729143a6` fixed it. Verify the base every time.
- `wasm-pack` is **not** in this worktree (`apps/editor/node_modules` is not installed).
  The build script honors a `WASM_PACK` env var; point it at the shared checkout's copy:
  `WASM_PACK=<colombo>/subsystems/clue-design/apps/editor/node_modules/.bin/wasm-pack`
  (v0.13.1). Prepending to PATH does not help — the script uses an absolute default.
- Python venv is the **repo root** `.venv` after `uv sync --frozen`; from
  `subsystems/clue-design` that is `../../.venv/bin/python`.
- `pytest -q` here prints no summary line (suppressed by config); check `$?`.

## Residuals — RELATED but deliberately OUT OF SCOPE

1. **The P1.1 contrast floor is 3.0, which is lenient.** It is WCAG AA for *large* text
   only; normal-size body text wants 4.5. It is precisely why this bug survived: the role's
   dark-on-brand pair scored ~3.4:1 in the live run and sailed through. Raising it is
   entangled with `LUMB0807` governance semantics (the governance diagnostic and the
   resolution-time correction would start disagreeing about what counts as legible), so it
   was explicitly excluded here. **Unowned.** Anyone raising it must reconcile both
   surfaces at once and re-baseline the `scene_brand_governance_flags_insufficient_text_contrast`
   expectations.
2. **The kit's `type.display` bakes `color: text.primary`, from stripecdn provenance.**
   A *display* role hard-baking a dark text color is what made the collision reachable at
   all — a display role is exactly the one most likely to sit on a branded/inverted ground.
   Whether roles should bake color at all (vs. leaving it to `on-color` pairing, which the
   color-craft wave just landed) is a **kit/design-knowledge** question, not an engine one.
   This fix makes the baked color harmless when the author disagrees, but it does not make
   the baking right. **Unowned.**
3. **The `text_token_honesty` "recolor detaches the role" rule is now partly redundant.**
   With precedence fixed, an editor recolor no longer *needs* to clear `style_token` to
   survive. Keeping the detach means a user who recolors also loses the role's future
   typography updates — arguably a worse outcome than before. Not changed here (it is an
   editor-semantics decision with its own tests and its own owner), but it should be
   revisited now that the underlying reason for it is gone.
4. **The design subsystem's `subsystems/clue-design/` is the copy fixed here.** Unlike the
   AD4.C F9 note in CLAUDE.md, there is no second divergent copy of `brand.rs` — the engine
   lives only here and is consumed by the platform via wasm/helper. No cross-copy residual.
