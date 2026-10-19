# Brand Capture Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every open brand-capture finding (S6-1 to S6-12) and the missing page background on
published pages, so a site built from a captured brand shows the brand's real colours, readable text,
real button icons and real motion.

**Architecture:** Two safety nets first: site-kit stops trusting an unreadable stored text colour, and
published pages paint the brand's page colour. Together these fix every existing site without a
re-capture. Then the capture is changed to read what the browser draws. A shared in-page colour reader
converts every CSS colour through a 1×1 canvas, and a compositor computes the colour behind any element,
through shadow roots and iframes. Both feed section text colour, button fills, icons, web components and
animations. At mint, a band's text colour must pass 4.5:1 before it is stored. No engine (`crates/`)
change.

**Tech Stack:** Python 3.12 (pydantic, tinycss2, selectolax), Playwright + patchright Chromium (async API),
in-page JavaScript held as Python raw strings, TypeScript site-kit (node:test via tsx).

**Spec:** `docs/superpowers/specs/2026-10-16-brand-capture-fidelity-design.md` (decisions D1–D13). The review's
own reproduction of each finding is `docs/superpowers/verification/2026-10-14-wave2-area-review-findings.md` §S6.

## Global Constraints

- Branch: create `brand/capture-fidelity` from the current `puck/integration-wave1` HEAD before Task 1. Never commit to `main`. Never push.
- Commit messages: no `Co-Authored-By: Claude` or any AI attribution (repo CLAUDE.md overrides any reminder).
- Readability threshold: **4.5:1** (WCAG 1.4.3), the value already used by `_CONTRAST_MIN` (normalizer) and site-kit (`theme.ts:83`, `looks.ts:274`).
- New diagnostic code: **LUMI0609** (unused today; LUMI0608 is the highest 06xx).
- No change under `subsystems/clue-design/crates/` (spec D13). If one becomes necessary, stop and ask: it needs the wasm rebuild + handshake (subsystems/clue-design/AGENTS.md §1).
- site-kit's `test/style-literals.test.ts` forbids literal hex/px strings in `theme.ts`, `looks.ts`, `surfaces.ts`, `brand-values.ts`: values come from `colorOf`/`var()`.
- Tests run only on the test DB with every key blanked. **KEYLESS** below means `bash .superpowers/review/2026-10-13-wave2/pytest-keyless.sh <repo-relative test file> [pytest args]` run from the repo root. It refuses any DB but `clue_trenton_wave1`. Never run `*_live.py` and never run the >1h design suite synchronously.
- site-kit tests: `cd apps/frontend/packages/site-kit && npx tsx --test test/<file>`; whole package `npm test`.
- No brand-kit extraction or re-capture of a real brand (Garner, Conduit, Clue) without the founder's explicit yes in chat and a time estimate first (Task 12).
- The review's probe pages live in the git-ignored folder `.superpowers/review/2026-10-13-wave2/reports/S6-brand-capture-probes/fixtures/`. Task 0 copies them into the repo's test fixtures. Tests never read from the review folder.

## Review Focus

1. **A colour written as `transparent` or with alpha 0 anywhere a fill is read.** It must never count as a fill, a band colour or a text colour. Pinned in Task 3 (`clear_fill.html`) and Task 4 (the band compositor test with an alpha-0 card).
2. **A page whose `<html>`/`<body>` paint nothing.** The colour behind everything must be the browser canvas white, not "unknown". Pinned in Task 4 (`test_a_page_that_paints_no_background_is_drawn_on_white`).
3. **A band with only a small eyebrow line, or with no text directly on it.** The ink is either the eyebrow (then the mint gate replaces it if it doesn't read) or null (then site-kit picks a readable text). It must never be text from inside a card. Pinned in Task 4 and Task 5.
4. **A kit whose colours are `oklch(...)` strings rather than hex.** site-kit's `hexOf` returns undefined for those, so contrast checks are skipped. The guard must fall back to the existing behaviour, never crash. Pinned in Task 1 (`an oklch pair is left to the existing choice`).
5. **Icons whose paint uses `url(#gradient)` or an alpha colour.** A `url(` paint is dropped (the cleaner refuses it), and an alpha colour is kept as `#RRGGBBAA`. The icon is never refused whole for it. Pinned in Task 6.

---

## Task 0: Branch and fixtures

**Files:**
- Create: `subsystems/clue-design/apps/api/tests/fixtures/capture/fidelity/` (6 HTML files copied)

- [ ] **Step 1: Create the branch**

```bash
git switch -c brand/capture-fidelity
git log --oneline -1
```

- [ ] **Step 2: Copy the review's probe pages into the repo's capture fixtures**

```bash
SRC=.superpowers/review/2026-10-13-wave2/reports/S6-brand-capture-probes/fixtures
DST=subsystems/clue-design/apps/api/tests/fixtures/capture/fidelity
mkdir -p "$DST"
cp "$SRC/s6_band_ink.html" "$DST/band_ink.html"
cp "$SRC/s6_tailwind_v4.html" "$DST/tailwind_v4.html"
cp "$SRC/s6_icons.html" "$DST/icons.html"
cp "$SRC/s6_shadow_iframe_anim.html" "$DST/shadow_iframe_anim.html"
cp "$SRC/s6_clear_fill.html" "$DST/clear_fill.html"
cp "$SRC/s6_overlay_reveal.html" "$DST/overlay_reveal.html"
ls "$DST"
```
Expected: the six files listed. Each file's top comment still says "S6 probe" — leave it, it names the finding it reproduces.

- [ ] **Step 3: Commit**

```bash
git add subsystems/clue-design/apps/api/tests/fixtures/capture/fidelity
git commit -m "brand capture: the review's six probe pages become capture test fixtures"
```

---

## Task 1: site-kit safety net — readable band text and a painted page

Fixes what people see on every existing kit, with no re-capture (spec D5, D6; S6-1's draw side; walk defect 4).

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/surfaces.ts:49-58` (`inkRole`)
- Modify: `apps/frontend/packages/site-kit/src/theme.ts:204` (`.brand-root` rule) and add `pageCanvasCss`
- Modify: `apps/frontend/packages/site-kit/src/render-core.tsx:15,95`
- Test: `apps/frontend/packages/site-kit/test/contrast.test.ts`, `test/theme.test.ts`, `test/render-core.test.tsx`
- Regenerate: `subsystems/clue-design/apps/api/tests/fixtures/site/probe_page.html` (via `test/fixtures/write-probe-page.tsx`)

**Interfaces:**
- Produces: `inkRole(brand, surface)` (unchanged signature) now returns the kit pair only when it reads. New `pageCanvasCss(brand: BrandData): string` exported from `src/theme.ts`.

- [ ] **Step 1: Write the failing tests** — append to `test/contrast.test.ts` (it already imports `kitBrand`, `withColors`, `cascade`, `ratio`; add `inkRole, isDarkSurface` to the `../src/surfaces` import):

```ts
test("S6-1: a band whose stored text colour does not read takes the readable one, everywhere inkRole is read", () => {
  // probe.minted pairs text.band.ffffff (#111111) with surface.band.ffffff; make the stored text the
  // orange eyebrow the capture used to take (#F5A623 on white is 2.0:1).
  const brand = withColors(kitBrand("probe.minted"), { "text.band.ffffff": "#F5A623" });
  assert.equal(inkRole(brand, "surface.band.ffffff"), "text.primary");
  const band = cascade(brand).on("surface.band.ffffff");
  assert.ok(ratio(band.ink, band.bg) >= 4.5, `${band.ink} on ${band.bg}`);
});

test("S6-1: a dark band whose stored text is a card's dark grey takes the light text, and is dark", () => {
  const brand = withColors(kitBrand("probe.minted"), { "surface.band.ffffff": "#0B2545", "text.band.ffffff": "#222222" });
  assert.equal(inkRole(brand, "surface.band.ffffff"), "text.inverse");
  assert.equal(isDarkSurface(brand, "surface.band.ffffff"), true);
});

test("S6-1: a stored text colour that reads is kept", () => {
  assert.equal(inkRole(kitBrand("probe.minted"), "surface.band.ffffff"), "text.band.ffffff");
});

test("S6-1: an oklch pair is left to the existing choice (no hex, no contrast maths)", () => {
  const brand = structuredClone(kitBrand("probe.minted"));
  const colors = (brand.kit as { tokens: { colors: Record<string, { value: Record<string, unknown> }> } }).tokens.colors;
  colors["text.band.ffffff"] = { ...colors["text.band.ffffff"], value: { ...colors["text.band.ffffff"].value, default: { kind: "oklch", l: 0.2, c: 0, h: 0 } } };
  assert.doesNotThrow(() => inkRole(brand, "surface.band.ffffff"));
});
```

Append to `test/theme.test.ts`:

```ts
test("walk defect 4: the brand root paints the page colour and its text, so gaps between sections are the page", () => {
  const css = themeCss(kitBrand("probe.minted"));
  const root = ruleOf(css, ".brand-root");
  assert.match(root, /background-color:var\(--brand-surface-page\)/);
  assert.match(root, /(?:^|[;{])color:var\(--brand-on-surface-page\)/);
});

test("walk defect 4: the document canvas is the page colour with a matching colour scheme", () => {
  const light = pageCanvasCss(kitBrand("probe.minted"));
  assert.match(light, /^html\{background-color:#[0-9A-F]{6};color:#[0-9A-F]{6,8};color-scheme:light\}$/);
  const dark = pageCanvasCss(withColor(withColor(kitBrand("probe.minted"), "surface.page", "#0B0B0B"), "text.primary", "#F5F5F5"));
  assert.match(dark, /background-color:#0B0B0B/);
  assert.match(dark, /color-scheme:dark/);
});
```
(add `pageCanvasCss` to that file's `../src/theme` import.)

In `test/render-core.test.tsx`, replace the exact head assertion in "a stored site renders every route as a document…" with:

```ts
    assert.ok(home.startsWith('<!doctype html><html lang="en"><head><title>Garner Health for Syracuse City School District</title><style data-clue-page="">html{background-color:#'), home.slice(0, 260));
    assert.ok(home.includes('</style></head><body>'), home.slice(0, 400));
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/contrast.test.ts test/theme.test.ts test/render-core.test.tsx`
Expected: FAIL. `inkRole` returns `text.band.ffffff` where `text.primary` is expected; `pageCanvasCss` is not exported; the head has no `data-clue-page` style.

- [ ] **Step 3: Implement**

`src/surfaces.ts` — replace `inkRole` (lines 49-58):

```ts
/** The colour role text takes on a surface: the kit's contrast pair when it reads there (4.5:1,
 * WCAG 1.4.3), else the better of text.primary and text.inverse. A pair that does not read is a
 * mis-measured one (S6-1: the capture once took a band's first text, an eyebrow or a card's words);
 * the page must never draw it. A pair whose colours are not hex (oklch) is kept as before. */
export function inkRole(brand: BrandData, surface: string): string | undefined {
  const bg = hexOf(brand, surface);
  if (!bg) return undefined;
  const pairs = (brand.kit as { constraints?: { contrast_pairs?: { background: string; foreground: string }[] } }).constraints?.contrast_pairs ?? [];
  const pair = pairs.find((p) => p.background === surface && hexOf(brand, p.foreground));
  if (pair && contrast(bg.slice(0, 7), hexOf(brand, pair.foreground)!.slice(0, 7)) >= 4.5) return pair.foreground;
  return readableInk(brand, bg);
}
```

`src/theme.ts` — line 204 becomes:

```ts
  // The root paints the page itself (walk defect 4): a gap between sections, or a section that sets no
  // surface, shows the brand's page colour and text, never the browser's default canvas.
  const paintsPage = colorOf(brand, "surface.page") !== undefined;
  lines.push(rule(".brand-root", {
    ...root, ...(local.get("surface.page") ?? {}),
    "background-color": paintsPage ? `var(--brand-${colorVar("surface.page")})` : undefined,
    color: paintsPage ? inkOn("surface.page") : undefined,
  }));
```

and add, after `themeCss`:

```ts
/** The document's own canvas (walk defect 4): the brand page colour and its text on `html`, so
 * overscroll and the space under a short page never show the browser's default — near black in a
 * dark-mode browser — and `color-scheme` tells the browser which way to draw its own controls.
 * Literal values: the `--brand-*` variables are declared on `.brand-root`, which `html` cannot see.
 * Empty for a kit with no page colour. */
export function pageCanvasCss(brand: BrandData): string {
  const page = colorOf(brand, "surface.page");
  if (!page) return "";
  return rule("html", {
    "background-color": page,
    color: colorOf(brand, inkRole(brand, "surface.page")),
    "color-scheme": isDarkSurface(brand, "surface.page") ? "dark" : "light",
  });
}
```
(`colorOf` is already imported from `./brand-values`; `inkRole`/`isDarkSurface` from `./surfaces`.)

`src/render-core.tsx` — import `pageCanvasCss` alongside `tailwindThemeCss` (line 15) and change line 95:

```ts
    const canvas = pageCanvasCss(input.brand);
    const head = `<title>${escapeHtml(title)}</title>${canvas ? `<style data-clue-page="">${canvas}</style>` : ""}`;
    const html = `<!doctype html><html lang="en"><head>${head}</head><body>${body}</body></html>`;
```

- [ ] **Step 4: Regenerate the probe page fixture and run the package**

```bash
cd apps/frontend/packages/site-kit
npx tsx test/fixtures/write-probe-page.tsx
npm test
```
Expected: all pass. `test/probe-page.test.tsx` compares against the regenerated `subsystems/clue-design/apps/api/tests/fixtures/site/probe_page.html`. `test/live-page.test.tsx` still passes, because the new style is in `<head>` and its assertions are on `<body>`.

- [ ] **Step 5: Check the app's Brand page tests that read `inkRole`**

```bash
cd apps/frontend && npx tsx --test src/features/brand-context/model/*.test.ts
```
Expected: pass. If an assertion pinned an unreadable band text colour from a fixture kit, change it to the readable one and name the finding in the assertion message (`S6-1`).

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/packages/site-kit apps/frontend/src/features/brand-context subsystems/clue-design/apps/api/tests/fixtures/site/probe_page.html
git commit -m "site-kit: a stored band text colour is used only when it reads; pages paint the brand page colour"
```

---

## Task 2: The Python colour parser reads CSS Color 4 functions

Stylesheet-declared colours (custom properties, declared roles, gradient stops, box-shadow colours) are
parsed from CSS text. They need the newer formats too (spec D2; S6-3's parser half). These conversions
were checked against Chromium 149's painted pixels on 2026-10-16, and every value below matched exactly.

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/css_color4.py`
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/parse.py:348` (before the final `return None` of `parse_color_value`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py:1241-1253` (`_take_color`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/rendered.py:215` (gradient stop regex in `_PROBE_JS`)
- Test: `subsystems/clue-design/apps/api/tests/test_css_color4.py`

**Interfaces:**
- Produces: `css_color4.COLOR4_FUNCTIONS: tuple[str, ...]` and `css_color4.color4_to_hex(name: str, parts: list[str]) -> str | None` (returns `#RRGGBB`; `None` when unreadable). `parse_color_value("oklch(…)", {})` → `#RRGGBB` or `#RRGGBBAA`.

- [ ] **Step 1: Write the failing test** — `subsystems/clue-design/apps/api/tests/test_css_color4.py`:

```python
"""CSS Color 4 colour functions read the way Chromium paints them (S6-3). Expected values are the
pixels Chromium 149 painted for each colour on 2026-10-16; the parity test re-asks the browser."""

from __future__ import annotations

import asyncio

import pytest

from lumen_ingestion.capture.geometry import _parse_box_shadow, _pointer
from lumen_ingestion.capture.parse import parse_color_value

PAINTED = {
    "oklch(0.546 0.245 262.881)": "#155DFC",   # Tailwind v4 blue-600
    "oklch(0.627 0.194 149.214)": "#00A63E",   # Tailwind v4 green-600
    "oklch(0.21 0.034 264.665)": "#101828",    # Tailwind v4 gray-900
    "oklch(0.623 0.214 259.815)": "#2B7FFF",
    "oklch(0.985 0 0)": "#FAFAFA",
    "oklch(0.7 0.4 30)": "#FF0000",            # out of gamut: clipped, as Chromium paints it
    "oklab(0.6 0.1 -0.1)": "#9F63BA",
    "lab(50 40 30)": "#BB5846",
    "lch(50 40 30)": "#B25D57",
    "hwb(120 10% 20%)": "#1ACC1A",
    "color(srgb 0.2 0.4 0.6)": "#336699",
    "color(display-p3 1 0 0)": "#FF0000",
}


@pytest.mark.parametrize("css, expected", sorted(PAINTED.items()))
def test_a_css_color4_colour_is_the_hex_chromium_paints(css: str, expected: str) -> None:
    assert parse_color_value(css, {}) == expected


def test_percentages_units_and_none_are_read() -> None:
    assert parse_color_value("oklch(54.6% 61.25% 262.881deg)", {}) == "#155DFC"
    assert parse_color_value("oklch(0.546 0.245 4.588rad)", {}) == "#155DFC"
    assert parse_color_value("oklch(0.985 0 none)", {}) == "#FAFAFA"


def test_alpha_is_kept_and_a_var_alpha_is_followed() -> None:
    opaque = parse_color_value("oklch(0.5 0.1 180)", {})
    assert parse_color_value("oklch(0.5 0.1 180 / 0.5)", {}) == opaque + "80"
    assert parse_color_value("oklch(0.5 0.1 180 / var(--a))", {"--a": "25%"}) == opaque + "40"


def test_an_unreadable_color4_value_is_one_skipped_swatch_with_a_reason() -> None:
    diagnostics: list[dict] = []
    assert parse_color_value("oklch(bogus 0 0)", {}, diagnostics=diagnostics) is None
    assert parse_color_value("color(rec2020 1 0 0)", {}, diagnostics=diagnostics) is None
    assert [d["code"] for d in diagnostics] == ["LUMI0511", "LUMI0511"]


def test_a_box_shadow_coloured_in_oklch_keeps_its_colour_and_lengths() -> None:
    [sample] = _parse_box_shadow("oklch(0.21 0.034 264.665) 0px 4px 12px 0px", _pointer("https://x.test/", "shadow"))
    assert (sample.color, sample.y, sample.blur) == ("#101828", 4.0, 12.0)


def test_the_parser_agrees_with_the_browser() -> None:
    values = sorted(PAINTED) + ["oklch(0.4 0.15 30)", "lab(80 -20 60)", "lch(30 60 250)", "oklab(0.3 -0.05 0.08)",
                                "color(display-p3 0.2 0.6 0.3)", "color(srgb-linear 0.1 0.5 0.9)", "hwb(300 0% 0%)"]
    painted = asyncio.run(_paint(values))
    for value, pixel in zip(values, painted):
        got = parse_color_value(value, {})
        assert got is not None, value
        channels = [int(got[i:i + 2], 16) for i in (1, 3, 5)]
        assert max(abs(a - b) for a, b in zip(channels, pixel)) <= 1, (value, got, pixel)


async def _paint(values: list[str]) -> list[list[int]]:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"chromium unavailable: {error}")
        try:
            page = await browser.new_page()
            return await page.evaluate(
                """(values) => { const c = document.createElement('canvas'); c.width = c.height = 1;
                const ctx = c.getContext('2d', { willReadFrequently: true });
                return values.map((v) => { ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = '#000'; ctx.fillStyle = v;
                ctx.fillRect(0, 0, 1, 1); return Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3); }); }""",
                values,
            )
        finally:
            await browser.close()
```
(`ShadowSample`, `lumen_ingestion/evidence.py:221-235`, has the fields `x`, `y`, `blur`, `spread`, `color`, `opacity`, `pointer`.)

- [ ] **Step 2: Run to verify it fails**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_css_color4.py`
Expected: FAIL. Every `PAINTED` case returns `None`.

- [ ] **Step 3: Write `lumen_ingestion/css_color4.py`**

```python
"""CSS Color 4 colour functions → the sRGB hex Chromium paints (review finding S6-3).

Tailwind v4 and shadcn/ui write every colour as `oklch()`; other sites use `lab()`, `lch()`,
`hwb()` and `color(display-p3 …)`. The browser paints each by converting to sRGB and clipping any
channel outside 0..1 (it does not reduce chroma), so this module does the same — checked against
Chromium 149's painted pixels (tests/test_css_color4.py). Channels only: the alpha slot is the
caller's (`capture.parse.parse_color_value` reads it, following `var()`).
"""

from __future__ import annotations

import math

from .colorspace import _linear_to_srgb, _srgb_to_linear, oklab_to_linear

COLOR4_FUNCTIONS = ("oklch", "oklab", "lch", "lab", "hwb", "color")

# CSS Color 4 sample-code matrices (https://www.w3.org/TR/css-color-4/#color-conversion-code).
_XYZ_D65_TO_LINEAR_SRGB = (
    (3.2409699419045226, -1.537383177570094, -0.4986107602930034),
    (-0.9692436362808796, 1.8759675015077202, 0.04155505740717559),
    (0.05563007969699366, -0.20397695888897652, 1.0569715142428786),
)
_D50_TO_D65 = (
    (0.955473421488075, -0.02309845494876471, 0.06325924320057072),
    (-0.0283697093338637, 1.0099953980813041, 0.021041441191917323),
    (0.012314014864481998, -0.020507649298898964, 1.330365926242124),
)
_LINEAR_P3_TO_XYZ_D65 = (
    (0.4865709486482162, 0.26566769316909306, 0.1982172852343625),
    (0.2289745640697488, 0.6917385218365064, 0.079286914093745),
    (0.0, 0.04511338185890264, 1.043944368900976),
)
_D50_WHITE = (0.3457 / 0.3585, 1.0, (1.0 - 0.3457 - 0.3585) / 0.3585)
_HUE_UNITS = {"deg": 1.0, "grad": 0.9, "rad": 180.0 / math.pi, "turn": 360.0}


def _mul(matrix, vector) -> tuple[float, float, float]:
    return tuple(sum(matrix[row][col] * vector[col] for col in range(3)) for row in range(3))  # type: ignore[return-value]


def _number(token: str, percent_of: float) -> float:
    """A channel: `none` is 0, a percentage is a share of `percent_of`. Raises ValueError."""
    text = token.strip().lower()
    if text == "none":
        return 0.0
    if text.endswith("%"):
        return float(text[:-1]) / 100.0 * percent_of
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(token)
    return value


def _hue(token: str) -> float:
    text = token.strip().lower()
    if text == "none":
        return 0.0
    for unit, factor in _HUE_UNITS.items():
        if text.endswith(unit):
            return float(text[: -len(unit)]) * factor
    return float(text)


def _channel(value: float) -> int:
    return max(0, min(255, round(max(0.0, min(1.0, value)) * 255)))


def _srgb_hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(_channel(c) for c in rgb)


def _linear_hex(linear) -> str:
    return _srgb_hex([_linear_to_srgb(max(0.0, min(1.0, c))) for c in linear])


def _lab_to_linear(lightness: float, a: float, b: float) -> tuple[float, float, float]:
    kappa, epsilon = 24389 / 27, 216 / 24389
    f1 = (lightness + 16) / 116
    f0, f2 = a / 500 + f1, f1 - b / 200
    x = f0 ** 3 if f0 ** 3 > epsilon else (116 * f0 - 16) / kappa
    y = f1 ** 3 if lightness > kappa * epsilon else lightness / kappa
    z = f2 ** 3 if f2 ** 3 > epsilon else (116 * f2 - 16) / kappa
    xyz_d50 = (x * _D50_WHITE[0], y * _D50_WHITE[1], z * _D50_WHITE[2])
    return _mul(_XYZ_D65_TO_LINEAR_SRGB, _mul(_D50_TO_D65, xyz_d50))


def _hwb_hex(hue: float, white: float, black: float) -> str:
    if white + black >= 1:
        grey = white / (white + black)
        return _srgb_hex((grey, grey, grey))
    def channel(n: int) -> float:
        k = (n + hue / 30) % 12
        pure = 0.5 - 0.5 * max(-1.0, min(k - 3, 9 - k, 1.0))
        return pure * (1 - white - black) + white
    return _srgb_hex((channel(0), channel(8), channel(4)))


def color4_to_hex(name: str, parts: list[str]) -> str | None:
    """`#RRGGBB` for the channels of one CSS Color 4 function, or None when they are unreadable or
    name a colour space we do not convert."""
    try:
        if name == "color":
            if len(parts) < 4:
                return None
            space, values = parts[0].strip().lower(), [_number(p, 1.0) for p in parts[1:4]]
            if space == "srgb":
                return _srgb_hex(values)
            if space == "srgb-linear":
                return _linear_hex(values)
            if space == "display-p3":
                linear = [math.copysign(_srgb_to_linear(abs(v)), v) for v in values]
                return _linear_hex(_mul(_XYZ_D65_TO_LINEAR_SRGB, _mul(_LINEAR_P3_TO_XYZ_D65, linear)))
            return None
        if len(parts) < 3:
            return None
        if name == "oklab":
            return _linear_hex(oklab_to_linear((_number(parts[0], 1.0), _number(parts[1], 0.4), _number(parts[2], 0.4))))
        if name == "oklch":
            lightness, chroma, hue = _number(parts[0], 1.0), _number(parts[1], 0.4), math.radians(_hue(parts[2]))
            return _linear_hex(oklab_to_linear((lightness, chroma * math.cos(hue), chroma * math.sin(hue))))
        if name == "lab":
            return _linear_hex(_lab_to_linear(_number(parts[0], 100.0), _number(parts[1], 125.0), _number(parts[2], 125.0)))
        if name == "lch":
            lightness, chroma, hue = _number(parts[0], 100.0), _number(parts[1], 150.0), math.radians(_hue(parts[2]))
            return _linear_hex(_lab_to_linear(lightness, chroma * math.cos(hue), chroma * math.sin(hue)))
        if name == "hwb":
            return _hwb_hex(_hue(parts[0]) % 360, _number(parts[1], 100.0) / 100.0, _number(parts[2], 100.0) / 100.0)
    except (ValueError, OverflowError):
        return None
    return None
```

- [ ] **Step 4: Teach `parse_color_value` the functions** — in `capture/parse.py`, add `from ..css_color4 import COLOR4_FUNCTIONS, color4_to_hex` to the imports, and replace the final `return None` of `parse_color_value` (line 348) with:

```python
    for name in COLOR4_FUNCTIONS:
        body = _function_body(text, (name,))
        if body is None:
            continue
        parts, alpha_slot = _split_color_args(body)
        hex6 = color4_to_hex(name, parts)
        if hex6 is None:
            _record_color_skip(diagnostics, f"unreadable {name}() value: {text}")
            return None
        if alpha_slot is not None:
            alpha = _alpha_or_opaque(alpha_slot, text, custom_props, diagnostics)
            if alpha < 255:
                return hex6 + "%02X" % alpha
        return hex6

    return None
```

- [ ] **Step 5: Shadows and gradient stops find the new functions** — `capture/geometry.py` `_take_color` (lines 1241-1253) becomes:

```python
_COLOR_CALL = re.compile(r"(?<![a-z-])(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.IGNORECASE)


def _take_color(text: str) -> tuple[str | None, str]:
    match = _COLOR_CALL.search(text)
    if match:
        end = text.find(")", match.start())
        if end >= 0:
            return text[match.start() : end + 1], text[: match.start()] + text[end + 1 :]
    for token in text.split():
        if token.startswith("#"):
            return token, text.replace(token, " ", 1)
    return None, text
```

In `capture/rendered.py` line 215 (inside `_PROBE_JS`), change the stop regex to:

```js
      const stops = cs.backgroundImage.match(/(?:rgba?|hsla?|hwb|oklab|oklch|lab|lch|color)\([^)]+\)/g) || [];
```

- [ ] **Step 6: Run the tests**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_css_color4.py`, then `KEYLESS subsystems/clue-design/apps/api/tests/test_ingestion_parse.py` if it exists (`ls subsystems/clue-design/apps/api/tests/ | grep -i parse` lists the parser's own tests; run each).
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/css_color4.py subsystems/clue-design/apps/api/lumen_ingestion/capture/parse.py subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py subsystems/clue-design/apps/api/lumen_ingestion/capture/rendered.py subsystems/clue-design/apps/api/tests/test_css_color4.py
git commit -m "ingestion: the colour parser reads oklch, oklab, lab, lch, hwb and color() the way Chromium paints them"
```

---

## Task 3: The capture reads every colour through the browser (S6-3, S6-7)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py` (new `COLOR_FN`; `GEOMETRY_JS` lines 150-188, 221, 243-245, 375; `shape_key` line ~806)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/states.py:50,89-140` (`LOOK_JS`)
- Create: `subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`
- Modify: `subsystems/clue-design/apps/api/tests/test_capture_style_states.py` (raw `rgb(...)` expectations become hex)

**Interfaces:**
- Produces, in-page (JS, defined by `COLOR_FN`, available to every probe that concatenates it): `hexOf(value) -> '#RRGGBB' | '#RRGGBBAA' | null`, `alphaOf(hex) -> number`, `paints(hex) -> bool`, `over(topHex, opaqueBottomHex) -> '#RRGGBB'`, `composedParent(node) -> Element | null`, `behindOf(el) -> '#RRGGBB' | null`.
- Produces, Python: `geometry.COLOR_FN: str`. Test helper `_capture(engine, fixture, extra_js=None) -> dict` and `_run(engine, fixture, extra_js=None) -> dict` in `test_capture_fidelity.py`, reused by Tasks 4, 6, 7, 8.

- [ ] **Step 1: Write the failing tests** — create `subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`:

```python
"""Brand capture fidelity (review findings S6-1 to S6-12): the real capture — GEOMETRY_JS, the state
pass, parse_geometry, attach_keyframes, the minter — over local pages, in Playwright's and
patchright's Chromium. Offline: file:// pages only, no model, no network."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from lumen_ingestion.capture.geometry import GEOMETRY_JS, parse_geometry
from lumen_ingestion.capture.motion import attach_keyframes
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.capture.states import REVEAL_BEFORE_JS, probe_states
from lumen_ingestion.normalizer.component_tokens import mint_component_tokens

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures" / "capture" / "fidelity"
GARNER = TESTS / "fixtures" / "ingestion" / "garner_kit.json"
ENGINES = ["playwright", "patchright"]


async def _capture(engine: str, fixture: str, extra_js: str | None = None) -> dict:
    if engine == "patchright":
        from patchright.async_api import async_playwright
    else:
        from playwright.async_api import async_playwright
    diagnostics: list[dict] = []
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"{engine} chromium unavailable: {error}")
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            await page.goto((FIXTURES / fixture).as_uri())
            await page.wait_for_timeout(800)
            reveal_before = await page.evaluate(REVEAL_BEFORE_JS)
            await page.evaluate("window.scrollTo(0, 0)")
            geometry = await page.evaluate(GEOMETRY_JS)
            extra = await page.evaluate(extra_js) if extra_js else None
            geometry["states"] = await probe_states(page, geometry, reveal_before=reveal_before, diagnostics=diagnostics)
        finally:
            await browser.close()
    return {"geometry": geometry, "diagnostics": diagnostics, "extra": extra}


def _css(fixture: str) -> str:
    text = (FIXTURES / fixture).read_text()
    return text.split("<style>", 1)[1].split("</style>", 1)[0]


def _run(engine: str, fixture: str, extra_js: str | None = None) -> dict:
    captured = asyncio.run(_capture(engine, fixture, extra_js))
    parsed = parse_geometry(captured["geometry"], page_url=f"https://{fixture}/")
    motion = attach_keyframes(parsed.motion, [Stylesheet(url=f"https://{fixture}/", text=_css(fixture))])
    kit = json.loads(GARNER.read_text())
    minted = mint_component_tokens(kit, parsed.styles, motion)
    return {"captured": captured, "parsed": parsed, "motion": motion, "kit": kit, "minted": minted}


def _buttons(run: dict) -> dict[str, object]:
    return {s.variant: s for s in run["parsed"].styles if s.surface == "button"}


@pytest.mark.parametrize("engine", ENGINES)
def test_s6_3_oklch_buttons_keep_their_own_fills_and_hovers(engine: str) -> None:
    buttons = _buttons(_run(engine, "tailwind_v4.html"))
    assert "solid.155dfc" in buttons and "solid.00a63e" in buttons, sorted(buttons)
    assert "ghost.none" not in buttons, sorted(buttons)
    assert buttons["solid.155dfc"].rest.background == "#155DFC"
    assert buttons["solid.155dfc"].hover is not None and buttons["solid.155dfc"].hover.background == "#1447E6"
    assert buttons["solid.047464"].hover is not None and buttons["solid.047464"].hover.background is not None


def test_s6_3_an_oklch_band_is_a_band_with_its_oklch_text() -> None:
    # tailwind_v4.html's band sits outside <main>, where the section reader never looks, so the band
    # case is its own page: two sections in <main>, the first painted in oklch.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_content(
                '<body style="margin:0"><main>'
                '<section style="background:oklch(0.21 0.034 264.665);color:oklch(0.985 0 0);min-height:240px">'
                '<h2>The statement band</h2><p>Light text on a dark band, written in oklch.</p></section>'
                '<section style="min-height:240px"><p>Next.</p></section></main></body>'
            )
            geometry = page.evaluate(GEOMETRY_JS)
        finally:
            browser.close()
    band = parse_geometry(geometry, page_url="https://oklch.test/").background_sequence[0]
    assert (band.background, band.ink) == ("#101828", "#FAFAFA")


@pytest.mark.parametrize("engine", ENGINES)
def test_s6_7_a_fully_transparent_fill_is_an_outline_not_a_filled_look(engine: str) -> None:
    variants = sorted(_buttons(_run(engine, "clear_fill.html")))
    assert "outline.ffffff" in variants and "outline.f5a623" in variants, variants
    assert not any(v.startswith("solid.ffffff00") for v in variants), variants
```
(`#1447E6` is what Chromium paints for `oklch(0.488 0.243 264.376)`, the fixture's blue hover. If the run reports a different hover hex, check it with `parse_color_value("oklch(0.488 0.243 264.376)", {})` from Task 2. That value is the source of truth; pin it.)

- [ ] **Step 2: Run to verify they fail**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`
Expected: FAIL. Both oklch CTAs come out as one `ghost.none`, and the clear fill is `solid.ffffff00`.

- [ ] **Step 3: Add `COLOR_FN` to `capture/geometry.py`**, directly after `FREEZE_MOTION_FN` (which ends line 141):

```python
#: The in-page colour reader every probe shares (review finding S6-3): each colour is drawn on a 1×1
#: canvas and read back, so oklch(), lab(), color(display-p3 …) and any later CSS colour syntax arrive
#: as the sRGB hex the page actually paints (Chromium clips out-of-gamut channels; so does this).
#: `behindOf` composites every background from an element up to the first opaque one — through slots,
#: shadow roots and same-origin iframes — onto the canvas default (white), and is null when a
#: background image sits in between: text on a photo or a gradient has no one colour behind it.
#: A hostile page can redefine canvas methods; it can only mislead its own capture.
COLOR_FN = r"""
  const __colorCanvas = document.createElement('canvas');
  __colorCanvas.width = 1; __colorCanvas.height = 1;
  const __colorCtx = __colorCanvas.getContext('2d', { willReadFrequently: true });
  const __colorCache = new Map();
  const __hex2 = (n) => n.toString(16).padStart(2, '0').toUpperCase();
  const hexOf = (value) => {
    if (value === undefined || value === null) return null;
    const text = String(value).trim();
    if (!text || text === 'none' || /^currentcolor$/i.test(text)) return null;
    if (__colorCache.has(text)) return __colorCache.get(text);
    let out = null;
    if (CSS.supports('color', text)) {
      __colorCtx.clearRect(0, 0, 1, 1);
      __colorCtx.fillStyle = '#000';
      __colorCtx.fillStyle = text;
      __colorCtx.fillRect(0, 0, 1, 1);
      const d = __colorCtx.getImageData(0, 0, 1, 1).data;
      out = d[3] === 0 ? '#00000000' : '#' + __hex2(d[0]) + __hex2(d[1]) + __hex2(d[2]) + (d[3] === 255 ? '' : __hex2(d[3]));
    }
    __colorCache.set(text, out);
    return out;
  };
  const alphaOf = (hex) => (!hex ? 0 : hex.length === 9 ? parseInt(hex.slice(7, 9), 16) / 255 : 1);
  const paints = (hex) => alphaOf(hex) > 0;
  const over = (top, bottom) => {
    const a = alphaOf(top);
    const ch = (i) => Math.round(parseInt(top.slice(i, i + 2), 16) * a + parseInt(bottom.slice(i, i + 2), 16) * (1 - a));
    return '#' + __hex2(ch(1)) + __hex2(ch(3)) + __hex2(ch(5));
  };
  const composedParent = (node) => {
    if (node.assignedSlot) return node.assignedSlot;
    if (node.parentElement) return node.parentElement;
    const root = node.getRootNode ? node.getRootNode() : null;
    if (root && root.host) return root.host;
    try {
      const view = node.ownerDocument && node.ownerDocument.defaultView;
      return view && view.frameElement ? view.frameElement : null;
    } catch (e) { return null; }
  };
  const behindOf = (el) => {
    const layers = [];
    for (let node = el; node; node = composedParent(node)) {
      if (node.nodeType !== 1) continue;
      const ncs = getComputedStyle(node);
      if (ncs.backgroundImage && ncs.backgroundImage !== 'none') return null;
      const fill = hexOf(ncs.backgroundColor);
      if (paints(fill)) { layers.push(fill); if (alphaOf(fill) >= 1) break; }
    }
    let base = '#FFFFFF';
    if (layers.length && alphaOf(layers[layers.length - 1]) >= 1) base = layers.pop();
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return base;
  };
"""
```

- [ ] **Step 4: Use it in `GEOMETRY_JS`**

1. Line 150: `""" + FREEZE_MOTION_FN + r"""` becomes `""" + FREEZE_MOTION_FN + COLOR_FN + r"""`.
2. Line 158: `const opaque = …` becomes:
   ```js
     // A colour that paints, as hex; null for none or fully transparent (S6-7: `rgba(255, 255, 255, 0)`
     // is no fill, whatever its channels say).
     const opaque = (v) => { const h = hexOf(v); return paints(h) ? h : null; };
   ```
3. Delete `effectiveBg` (lines 180-188).
4. In `look()` line 221: `color: cs.color || null,` becomes `color: hexOf(cs.color),`.
5. In `ctaAnchor`, lines 243-245 become:
   ```js
       const fill = opaque(cs.backgroundColor);
       const behind = behindOf(el.parentElement) || '#FFFFFF';  // the canvas default
       if (fill && over(fill, behind) !== behind) return true;
   ```
6. In the sections loop, line 375: `bg: effectiveBg(el),` becomes `bg: behindOf(el),`.

`grep -n "effectiveBg" subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py` must print nothing.

- [ ] **Step 5: `shape_key` refuses a transparent fill on old harvests too** — in `geometry.py` `shape_key`, `bg = _hex(entry.get("bg"))` becomes `bg = _opaque_hex(entry.get("bg"))`.

- [ ] **Step 6: Use it in `LOOK_JS`** — `capture/states.py` line 50 imports `COLOR_FN` too (`from .geometry import COLOR_FN, FREEZE_MOTION_FN, normalize_transform, state_targets`). `LOOK_JS` opens `r"""\n(el) => {\n  if (!el.isConnected) …` — split it after the `isConnected` line so it becomes:

```python
LOOK_JS = r"""
(el) => {
  if (!el.isConnected) throw new Error('the element has left the page');
""" + COLOR_FN + r"""
  const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? Math.round(n * 100) / 100 : null; };
```
(the rest unchanged up to the look object). In the look object, the colour keys become:

```js
    background: hexOf(cs.backgroundColor),
    color: hexOf(cs.color),
    label_color: host === el ? null : hexOf(hs.color),
    border_color: hexOf(cs.borderTopColor),
```
and further down `outline_color: hexOf(cs.outlineColor),` and, in the icon block, `look.icon_color = hexOf(is.color);`.

A transparent colour now arrives as `#00000000`, the same value `_look_fields(clears=True)` already writes for a state that clears a colour (`_CLEARED`). `look_delta` compares these strings exactly as it compared the raw ones.

- [ ] **Step 7: Run the new tests**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`
Expected: PASS (both engines).

- [ ] **Step 8: Update the raw-string expectations in `test_capture_style_states.py`.** The capture now reports hex. Replace each literal as follows, every occurrence (lines 95-364):

| was | now |
|---|---|
| `"rgb(3, 90, 78)"` | `"#035A4E"` |
| `"rgb(2, 63, 55)"` | `"#023F37"` |
| `"rgb(245, 166, 35)"` | `"#F5A623"` |
| `"rgb(255, 255, 255)"` | `"#FFFFFF"` |
| `"rgb(90, 47, 214)"` | `"#5A2FD6"` |
| `"rgb(8, 58, 108)"` | `"#083A6C"` |
| `"rgb(4, 116, 100)"` | `"#047464"` |
| `"rgb(0, 0, 0)"` | `"#000000"` |
| `"rgb(40, 36, 30)"` | `"#28241E"` |
| `"rgb(8, 66, 124)"` | `"#08427C"` |

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_style_states.py`
Expected: PASS. A failure on anything other than one of these literals is a real regression: analyse it, never weaken the assertion.

- [ ] **Step 9: Run the neighbouring capture suites**

Run each with KEYLESS: `test_ingestion_root_units.py`, `test_ingestion_geometry.py`, `test_ingestion_segmentation.py`, `test_capture_style_names.py`, `test_ingestion_measured_styles.py`, `test_ingestion_component_tokens.py`.
Expected: PASS. (`test_ingestion_segmentation.py` slices `GEOMETRY_JS` on the text `"sections.push({"`. That text is unchanged.)

- [ ] **Step 10: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py subsystems/clue-design/apps/api/lumen_ingestion/capture/states.py subsystems/clue-design/apps/api/tests/test_capture_fidelity.py subsystems/clue-design/apps/api/tests/test_capture_style_states.py
git commit -m "capture: every colour is read through the browser, so oklch buttons keep their fills and a transparent fill is no fill"
```

---

## Task 4: A section's text colour is the text on it (S6-1, capture side)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py:325-335` (`inkOf`) and the sections loop (`ink:` line ~377)
- Test: `subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`

**Interfaces:**
- Consumes: `behindOf`, `hexOf`, `alphaOf`, `over` from Task 3.
- Produces: the section record's `ink` is now the opaque `#RRGGBB` covering the most text area directly on the section's own backdrop, or null.

- [ ] **Step 1: Write the failing tests** — append to `test_capture_fidelity.py`:

```python
@pytest.mark.parametrize("engine", ENGINES)
def test_s6_1_a_bands_text_colour_is_its_heading_and_body_not_an_eyebrow_or_a_card(engine: str) -> None:
    bands = {b.background: b.ink for b in _run(engine, "band_ink.html")["parsed"].background_sequence}
    assert bands.get("#F3F0E8") == "#333333", bands   # the body copy outweighs the orange eyebrow
    assert bands.get("#0B2545") == "#FFFFFF", bands   # the white card's text is not on the navy band


def test_behind_of_composites_translucent_layers_and_skips_alpha_zero() -> None:
    from playwright.sync_api import sync_playwright

    from lumen_ingestion.capture.geometry import COLOR_FN

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                '<div id="band" style="background:#0B2545"><div id="clear" style="background:rgba(255,255,255,0)">'
                '<div id="glass" style="background:rgba(255,255,255,0.5)"><p id="t">x</p></div></div></div>'
            )
            got = page.evaluate("() => {" + COLOR_FN + "return [behindOf(document.getElementById('clear')), behindOf(document.getElementById('t'))]; }")
        finally:
            browser.close()
    assert got[0] == "#0B2545"
    assert got[1] == "#8592A2"   # 50% white over #0B2545, rounded per channel


def test_s6_1_a_band_whose_only_text_sits_in_a_card_has_no_ink() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_content(
                '<body style="margin:0"><main>'
                '<section style="background:#0B2545;min-height:240px"><div style="background:#fff;color:#222;padding:24px">'
                '<p>Only a quote, in a white card.</p></div></section>'
                '<section style="min-height:240px"><p>Next.</p></section></main></body>'
            )
            geometry = page.evaluate(GEOMETRY_JS)
        finally:
            browser.close()
    band = parse_geometry(geometry, page_url="https://card.test/").background_sequence[0]
    assert (band.background, band.ink) == ("#0B2545", None)


def test_a_page_that_paints_no_background_is_drawn_on_white() -> None:
    from playwright.sync_api import sync_playwright

    from lumen_ingestion.capture.geometry import COLOR_FN

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content('<p id="t">plain</p>')
            got = page.evaluate("() => {" + COLOR_FN + "return behindOf(document.getElementById('t')); }")
        finally:
            browser.close()
    assert got == "#FFFFFF"
```
(50% white over `#0B2545`: R = round(255·0.502 + 11·0.498) = 133 = 0x85, G = round(255·0.502 + 37·0.498) = 146 = 0x92, B = round(255·0.502 + 69·0.498) = 162 = 0xA2. Chromium stores 0.5 alpha as 128/255 = 0.502.)

- [ ] **Step 2: Run to verify the band test fails**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_fidelity.py -k "s6_1 or behind_of or paints_no"`
Expected: both `test_s6_1_…` FAIL (cream reports `#F5A623`, navy `#222222`; the card-only band reports `#222222`). The two `behindOf` tests already pass, because Task 3 built `behindOf`; they pin it.

- [ ] **Step 3: Replace `inkOf`** (geometry.py lines 325-335) with:

```js
  // The text colour a band carries (S6-1): of the text drawn directly on the band's own backdrop —
  // never text inside a card or panel that paints its own background — the colour covering the most
  // text area (characters × font size), so headings and body outweigh a small eyebrow line. A
  // translucent text colour is taken as it reads on the band. null when no text sits on the band.
  const inkOf = (el, bandBg) => {
    if (!bandBg) return null;
    const weights = new Map();
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node, seen = 0;
    while ((node = walker.nextNode()) && seen < 400) {
      const text = (node.textContent || '').trim();
      const host = node.parentElement;
      if (!text || !host) continue;
      seen += 1;
      const hcs = getComputedStyle(host);
      if (hcs.visibility === 'hidden' || parseFloat(hcs.opacity) === 0) continue;
      const r = host.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      if (behindOf(host) !== bandBg) continue;
      const ink = hexOf(hcs.color);
      if (!paints(ink)) continue;
      const drawn = alphaOf(ink) >= 1 ? ink : over(ink, bandBg);
      weights.set(drawn, (weights.get(drawn) || 0) + text.length * (parseFloat(hcs.fontSize) || 16));
    }
    let best = null, most = 0;
    for (const [ink, weight] of weights) { if (weight > most) { best = ink; most = weight; } }
    return best;
  };
```

and in the sections loop compute the backdrop once:

```js
    const backdrop = behindOf(el);
    sections.push({
      index: sections.length,
      tag: el.tagName.toLowerCase(),
      id: el.getAttribute('id'),
      classes: el.getAttribute('class'),
      top: r2(top),
      bg: backdrop,
      bgImage: bgImage,
      ink: inkOf(el, backdrop),
```
(The literal text `sections.push({` must stay exactly as is: `test_ingestion_segmentation.py` slices on it.)

- [ ] **Step 4: Run the tests**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`, then `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_style_states.py` (its `band["ink"] == "#FFFFFF"` check for the light-text band must still hold).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py subsystems/clue-design/apps/api/tests/test_capture_fidelity.py
git commit -m "capture: a section's text colour is the text drawn on it, weighted by size, never a card's or an eyebrow's alone"
```

---

## Task 5: A band text colour is stored only when it reads (S6-1, mint side)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/bands.py` (new `readable_ink`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/__init__.py:135-159,360-381`
- Modify: `subsystems/clue-design/scripts/build_site_kit_brand_fixtures.py:89-120` (the mirrored band step)
- Test: `subsystems/clue-design/apps/api/tests/test_ingestion_geometry.py`

**Interfaces:**
- Produces: `bands.readable_ink(band: BandSurface, candidates: list[str]) -> tuple[str, bool]`, which returns the ink to store and whether it is the measured one. `normalizer._band_ink(builder, band, *, measured: bool = True) -> str`. Diagnostic `LUMI0609`.

- [ ] **Step 1: Write the failing tests** — append to `test_ingestion_geometry.py` (it already has `_synthetic`, `_section`, `_CREATED_AT` and imports `normalize_evidence`; `normalize_evidence(...)` returns an object with `.brand_kit` and `.diagnostics`):

```python
def _normalized(evidence):
    return normalize_evidence(evidence, brand_kit_id="brand_kit_geometry", version=1, name="Geometry", created_at=_CREATED_AT)


def test_s6_1_a_band_text_colour_that_does_not_read_is_replaced_by_one_that_does() -> None:
    result = _normalized(_synthetic([
        _section(0, "rgb(255, 255, 255)", 900),
        {**_section(1, "rgb(243, 240, 232)", 700), "ink": "rgb(245, 166, 35)"},   # orange on cream, 1.78:1
        {**_section(2, "rgb(11, 37, 69)", 600), "ink": "rgb(34, 34, 34)"},        # dark grey on navy, 1.03:1
    ]))
    kit, diagnostics = result.brand_kit, result.diagnostics
    colors, pairs = kit["tokens"]["colors"], kit["constraints"]["contrast_pairs"]
    by_band = {p["background"]: p["foreground"] for p in pairs if p["background"].startswith("surface.band.")}
    from lumen_ingestion.colorspace import contrast_ratio
    for band, ink in by_band.items():
        ratio = contrast_ratio(colors[ink]["value"]["default"]["value"], colors[band]["value"]["default"]["value"])
        assert ratio >= 4.5, (band, ink, ratio)
    assert [d["code"] for d in diagnostics if d["code"] == "LUMI0609"] == ["LUMI0609", "LUMI0609"]
    assert "#F5A623" in next(d["message"] for d in diagnostics if d["code"] == "LUMI0609")


def test_s6_1_a_band_text_colour_that_reads_is_kept_as_measured() -> None:
    result = _normalized(_synthetic([
        _section(0, "rgb(255, 255, 255)", 900),
        {**_section(1, "rgb(40, 36, 30)", 600), "ink": "rgb(250, 245, 230)"},
    ]))
    assert result.brand_kit["tokens"]["colors"]["text.band.28241e"]["value"]["default"]["value"] == "#FAF5E6"
    assert not [d for d in result.diagnostics if d["code"] == "LUMI0609"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_ingestion_geometry.py -k s6_1`
Expected: the first FAILS (ratios 1.78 and 1.03, no LUMI0609); the second passes.

- [ ] **Step 3: `bands.readable_ink`** — append to `normalizer/bands.py` (add `from ..colorspace import contrast_ratio` to its imports):

```python
#: A band's text must read on it (WCAG 1.4.3), the normalizer's `_CONTRAST_MIN`.
READABLE_RATIO = 4.5


def readable_ink(band: BandSurface, candidates: list[str]) -> tuple[str, bool]:
    """The text colour to store for a band, and whether it is the one measured there (S6-1). The
    measured colour when it reads on the band; else the best-reading of `candidates` (the kit's
    text.primary and text.inverse); else black or white, whichever reads better. `band.ink_hex` must
    be set."""
    measured = str(band.ink_hex)
    if contrast_ratio(measured, band.hex) >= READABLE_RATIO:
        return measured, True
    options = [c[:7].upper() for c in candidates if c] + ["#FFFFFF", "#0B0F14"]
    best = max(options, key=lambda option: contrast_ratio(option, band.hex))
    return best, False
```

- [ ] **Step 4: Use it in the normalizer** — `normalizer/__init__.py`, import `readable_ink` with `build_band_surfaces`, and replace the `if band.ink_hex:` block (lines 153-154) with:

```python
        if band.ink_hex:
            candidates = [
                str(builder.colors[path]["value"]["default"].get("value") or "")
                for path in ("text.primary", "text.inverse") if path in builder.colors
            ]
            ink, measured = readable_ink(band, candidates)
            if not measured:
                diagnostics.append({
                    "code": "LUMI0609", "severity": "warning",
                    "message": (
                        f"the text measured on section background {band.hex} ({band.ink_hex}, ratio "
                        f"{contrast_ratio(band.ink_hex, band.hex):.2f}) does not read there; its text uses {ink}"
                    ),
                })
            band_pairs.append({
                "foreground": _band_ink(builder, replace(band, ink_hex=ink), measured=measured),
                "background": band.path, "min_ratio": 4.5,
            })
```
(add `from dataclasses import replace`). Change `_band_ink`'s signature and its minted description (lines 360-381):

```python
def _band_ink(builder: KitBuilder, band, *, measured: bool = True) -> str:
    """The colour token for a band's text: an exact match, alpha included (an ink first), else
    `text.band.<hex of the band>` — described as measured, or as chosen to read (S6-1)."""
    matches = sorted(
        (
            path for path, entry in builder.colors.items()
            if entry["value"]["default"].get("kind") == "hex"
            and opaque_hex(str(entry["value"]["default"].get("value") or "")) == band.ink_hex
        ),
        key=lambda path: (not path.startswith("text."), path),
    )
    if matches:
        return matches[0]
    path = "text.band." + band.path.rsplit(".", 1)[1]
    provenance = band.provenance.replace("section background", "text on section background")
    builder.add_color(
        path,
        RoleAssignment(band.ink_hex, "measured" if measured else "derived", provenance),
        None,
        confidence=MEASURED_CONFIDENCE,
        description="text measured on that section background" if measured
        else "text chosen to read on that section background (the measured text did not)",
    )
    return path
```
(`RoleAssignment.basis` accepts `"evidence" | "measured" | "derived" | "default"`, `normalizer/roles.py:47-55`.)

- [ ] **Step 5: Mirror the step in the fixture script** — `scripts/build_site_kit_brand_fixtures.py` `_add_bands` (lines 108-120) applies the same `readable_ink` (import it from `lumen_ingestion.normalizer.bands`) with `candidates` read from `colors`. Give `_band_ink` the same `measured` flag and description, so `test_the_fixture_band_step_adds_exactly_what_ingestion_adds` keeps holding. Then regenerate:

```bash
cd subsystems/clue-design && PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python scripts/build_site_kit_brand_fixtures.py && git status --short
```
Expected: no fixture change (the probe bands' inks `#111111` on white and white on `#014036` already read). A change means the gate replaced an ink. Inspect it before committing.

- [ ] **Step 6: Run the tests**

Run with KEYLESS: `test_ingestion_geometry.py`, `test_measured_components.py`, `test_ingestion_normalizer.py`, `test_ingestion_section_mint.py`, `test_ingestion_grammar_audit.py`.
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/normalizer subsystems/clue-design/scripts/build_site_kit_brand_fixtures.py subsystems/clue-design/apps/api/tests/test_ingestion_geometry.py
git commit -m "ingestion: a band's text colour is stored only when it reads there (LUMI0609 names the one replaced)"
```

---

## Task 6: Icons keep the paint and the size the page drew (S6-2 colour, S6-10)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/states.py:143-191` (`MOTION_JS`)
- Test: `subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`

**Interfaces:**
- Consumes: `COLOR_FN` (`hexOf`) from Task 3.
- Produces: `StyleIcon.svg` markup carries computed paint attributes, and sprite groups carry a `transform`. Unchanged schema.

- [ ] **Step 1: Write the failing tests** — append to `test_capture_fidelity.py`:

```python
def _icons(run: dict) -> dict[str, str]:
    return {s.variant: s.icon.svg for s in run["parsed"].styles if s.surface == "button" and s.icon and s.icon.svg}


@pytest.mark.parametrize("engine", ENGINES)
def test_s6_2_a_css_stroked_icon_keeps_its_stroke_and_follows_the_label(engine: str) -> None:
    icons = _icons(_run(engine, "icons.html"))
    stroke = icons["solid.ad1457"]
    root = stroke.split(">", 1)[0]
    assert 'fill="none"' in root and 'stroke="currentColor"' in root and 'stroke-width="2"' in root, stroke
    assert 'stroke-linecap="round"' in root and 'stroke-linejoin="round"' in root, stroke
    hero = icons["solid.00695c"]
    assert 'fill="currentColor"' in hero.split(">", 1)[0], hero


@pytest.mark.parametrize("engine", ENGINES)
def test_s6_10_a_sprite_icon_is_drawn_at_the_size_the_page_drew_it(engine: str) -> None:
    sprite = _icons(_run(engine, "icons.html"))["solid.283593"]
    assert 'viewBox="0 0 24 24"' in sprite and 'transform="translate(0 0) scale(2 2)"' in sprite, sprite


def test_the_captured_icons_draw_like_the_page() -> None:
    """Rendered on a dark button with white text, the captured markup paints white, at full size."""
    from playwright.sync_api import sync_playwright

    icons = _icons(_run("playwright", "icons.html"))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            out = {}
            for variant, markup in icons.items():
                sized = markup.replace("<svg", '<svg width="16" height="16"', 1)
                page.set_content(f'<div style="color:#fff;background:#222">{sized}</div>')
                out[variant] = page.evaluate("""() => { const p = document.querySelector('path');
                  const cs = getComputedStyle(p); const r = p.getBoundingClientRect();
                  return { fill: cs.fill, stroke: cs.stroke, w: Math.round(r.width) }; }""")
        finally:
            browser.close()
    assert out["solid.ad1457"]["stroke"] == "rgb(255, 255, 255)" and out["solid.ad1457"]["fill"] == "none", out
    assert out["solid.00695c"]["fill"] == "rgb(255, 255, 255)", out
    assert out["solid.283593"]["w"] >= 11, out   # the 12-unit arrow scaled into the 24-unit box: ~12px of 16


def test_an_icon_painted_through_a_gradient_or_in_a_translucent_colour_is_still_kept() -> None:
    from playwright.sync_api import sync_playwright

    from lumen_ingestion.capture.motion import clean_icon_svg
    from lumen_ingestion.capture.states import MOTION_JS

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                '<a id="b" href="#" style="color:#fff;background:#222;padding:12px 24px">Go '
                '<svg viewBox="0 0 24 24" style="width:16px;height:16px"><defs><linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient></defs>'
                '<path d="M5 12h14" style="fill:url(#g);stroke:rgba(255,255,255,0.5);stroke-width:2"/></svg></a>'
            )
            info = page.locator("#b").evaluate(MOTION_JS)["icon"]
        finally:
            browser.close()
    cleaned = clean_icon_svg(info["svg"])
    assert cleaned is not None and "url(" not in cleaned, info["svg"]
    assert 'stroke="#FFFFFF80"' in cleaned, cleaned
```

- [ ] **Step 2: Run to verify they fail**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_fidelity.py -k "s6_2 or s6_10 or draw_like"`
Expected: FAIL. The stroked icon has no stroke, and the sprite has no transform (it draws ~6px).

- [ ] **Step 3: Rewrite `MOTION_JS`'s icon reading** — in `capture/states.py`, `MOTION_JS` begins `(el) => {` followed by `_TRANSITIONS_FN`. Insert `COLOR_FN` right after `_TRANSITIONS_FN` (`""" + _TRANSITIONS_FN + COLOR_FN + r"""`). Then replace the `iconMarkup` function (the `// A sprite icon …` comment through `return copy.outerHTML.slice(0, 8192); };`) with:

```js
  // The icon as the page drew it (S6-2, S6-10). The cleaner keeps drawing attributes only — never
  // `class` or `style` — so the paint CSS gave the icon is written onto a copy as attributes: on each
  // element where it differs from its parent's, on the root where it differs from the initial value.
  // A fill or stroke equal to the icon's text colour is written `currentColor`, so the icon keeps
  // following the label's colour in every state and on every surface. A paint through `url(…)` is
  // left out (the cleaner refuses it). A sprite `<use>` becomes a group carrying the use's own paint,
  // scaled from the symbol's viewBox into the box the use drew (preserveAspectRatio honoured), so the
  // drawing keeps its size and place; the symbol's children keep their own attributes.
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const PAINT = ['fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit',
    'fill-rule', 'clip-rule', 'opacity', 'fill-opacity', 'stroke-opacity'];
  const INITIAL = { stroke: 'none', 'stroke-width': '1', 'stroke-linecap': 'butt', 'stroke-linejoin': 'miter',
    'stroke-miterlimit': '4', 'fill-rule': 'nonzero', 'clip-rule': 'nonzero', opacity: '1', 'fill-opacity': '1',
    'stroke-opacity': '1' };
  const r3 = (n) => Math.round(n * 1000) / 1000;
  const paintValue = (prop, raw, textColor) => {
    const v = String(raw || '').trim();
    if (!v) return null;
    if (prop === 'fill' || prop === 'stroke') {
      if (v === 'none') return 'none';
      if (v.indexOf('url(') >= 0) return null;
      const hex = hexOf(v);
      if (!hex) return null;
      return hex === textColor ? 'currentColor' : hex;
    }
    if (prop === 'stroke-width' || prop === 'stroke-miterlimit' || prop.endsWith('opacity')) {
      const n = parseFloat(v);
      return Number.isFinite(n) ? String(r3(n)) : null;
    }
    return v;
  };
  const writePaint = (src, dst, parentSrc, textColor) => {
    const cs = getComputedStyle(src);
    const ps = parentSrc ? getComputedStyle(parentSrc) : null;
    for (const prop of PAINT) {
      const value = paintValue(prop, cs.getPropertyValue(prop), textColor);
      if (value === null) continue;
      if (ps ? paintValue(prop, ps.getPropertyValue(prop), textColor) === value : INITIAL[prop] === value) continue;
      dst.setAttribute(prop, value);
    }
  };
  const lengthOf = (el, name, ref) => {
    const raw = el.getAttribute(name);
    if (raw === null || String(raw).trim() === '') return null;
    const n = parseFloat(raw);
    if (!Number.isFinite(n)) return null;
    return String(raw).trim().endsWith('%') ? (n / 100) * ref : n;
  };
  const viewBoxOf = (el) => {
    const vb = String(el.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
    return vb.length === 4 && vb.every(Number.isFinite) && vb[2] > 0 && vb[3] > 0 ? vb : null;
  };
  const useTransform = (use, target, symbol, outer) => {
    const x = lengthOf(use, 'x', outer.w) || 0, y = lengthOf(use, 'y', outer.h) || 0;
    const vb = symbol ? viewBoxOf(target) : null;
    if (!vb) return (x || y) ? `translate(${r3(x)} ${r3(y)})` : null;
    const w = lengthOf(use, 'width', outer.w), h = lengthOf(use, 'height', outer.h);
    const W = w === null ? outer.w : w, H = h === null ? outer.h : h;
    const par = String(target.getAttribute('preserveAspectRatio') || 'xMidYMid meet').trim().split(/\s+/);
    let sx = W / vb[2], sy = H / vb[3], tx = x - vb[0] * sx, ty = y - vb[1] * sy;
    if (par[0] !== 'none') {
      const s = par[1] === 'slice' ? Math.max(sx, sy) : Math.min(sx, sy);
      const fx = par[0].indexOf('xMid') >= 0 ? 0.5 : par[0].indexOf('xMax') >= 0 ? 1 : 0;
      const fy = par[0].indexOf('YMid') >= 0 ? 0.5 : par[0].indexOf('YMax') >= 0 ? 1 : 0;
      sx = sy = s;
      tx = x + (W - vb[2] * s) * fx - vb[0] * s;
      ty = y + (H - vb[3] * s) * fy - vb[1] * s;
    }
    if (r3(sx) === 1 && r3(sy) === 1 && r3(tx) === 0 && r3(ty) === 0) return null;
    return `translate(${r3(tx)} ${r3(ty)}) scale(${r3(sx)} ${r3(sy)})`;
  };
  const iconMarkup = (svg) => {
    const copy = svg.cloneNode(true);
    const textColor = hexOf(getComputedStyle(svg).color);
    const sources = [svg, ...Array.from(svg.querySelectorAll('*'))];
    const copies = [copy, ...Array.from(copy.querySelectorAll('*'))];
    sources.forEach((src, i) => { if (copies[i]) writePaint(src, copies[i], i === 0 ? null : src.parentElement, textColor); });
    const root = svg.getRootNode();
    const byId = (id) => (root && root.getElementById ? root.getElementById(id) : null) || svg.ownerDocument.getElementById(id);
    for (const use of Array.from(copy.querySelectorAll('use'))) {
      const ref = use.getAttribute('href') || use.getAttribute('xlink:href') || '';
      const target = ref.startsWith('#') ? byId(ref.slice(1)) : null;
      if (!target) continue;
      const symbol = target.tagName.toLowerCase() === 'symbol';
      if (symbol && !copy.hasAttribute('viewBox') && target.hasAttribute('viewBox')) {
        copy.setAttribute('viewBox', target.getAttribute('viewBox'));
      }
      const box = svg.getBoundingClientRect();
      const vb = viewBoxOf(copy);
      const outer = vb ? { w: vb[2], h: vb[3] }
        : { w: lengthOf(svg, 'width', box.width) || box.width, h: lengthOf(svg, 'height', box.height) || box.height };
      const group = document.createElementNS(SVG_NS, 'g');
      for (const prop of PAINT) if (use.hasAttribute(prop)) group.setAttribute(prop, use.getAttribute(prop));
      const transform = useTransform(use, target, symbol, outer);
      if (transform) group.setAttribute('transform', transform);
      const drawn = symbol ? Array.from(target.childNodes).map((child) => child.cloneNode(true)) : [target.cloneNode(true)];
      for (const child of drawn) group.appendChild(child);
      use.replaceWith(group);
    }
    return copy.outerHTML.slice(0, 8192);
  };
```

- [ ] **Step 4: Run the tests**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`, then `KEYLESS subsystems/clue-design/apps/api/tests/test_ingestion_measured_styles.py` and `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_style_states.py`.
Expected: PASS. Then run the A9 icon scenarios, which need the test DB (KEYLESS provides it):
`KEYLESS subsystems/clue-design/apps/api/tests/test_a9_scenarios.py -k "4d or 4f"`. Expected: PASS (4f's `viewBox="0 0 12 12"` still holds: that svg has no viewBox of its own, the symbol's is copied, and the identity scale writes no transform).

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/capture/states.py subsystems/clue-design/apps/api/tests/test_capture_fidelity.py
git commit -m "capture: button icons keep the paint CSS gave them, and sprite icons keep their size"
```

---

## Task 7: Buttons inside web components and iframes are measured (S6-8)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py` (`GEOMETRY_JS` enumeration loop, lines 252-296)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/states.py:361-363,393-423,467-481` (`_force`, `_probe_one`, `probe_states`)
- Test: `subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`

**Interfaces:**
- Produces: `states._probe_handle(page, idx) -> ElementHandle`, `states._node_id(cdp, idx) -> int` (raises `LookupError`), `states._force(cdp, idx, classes) -> None` (the `root` parameter is gone).

- [ ] **Step 1: Write the failing test** — append to `test_capture_fidelity.py`:

```python
@pytest.mark.parametrize("engine", ENGINES)
def test_s6_8_web_component_and_iframe_ctas_are_measured_with_their_hover(engine: str) -> None:
    buttons = _buttons(_run(engine, "shadow_iframe_anim.html"))
    assert "solid.047464" in buttons and "solid.1565c0" in buttons, sorted(buttons)
    assert buttons["solid.047464"].hover is not None and buttons["solid.047464"].hover.background == "#035A4E"
    assert buttons["solid.1565c0"].hover is not None and buttons["solid.1565c0"].hover.background == "#0D47A1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_fidelity.py -k s6_8`
Expected: FAIL (neither variant is present).

- [ ] **Step 3: Enumerate through shadow roots and iframes** — in `GEOMETRY_JS`, before `const seen = new Set();` (line ~286), add:

```js
  // Where the page's elements live (S6-8): the document, every open shadow root, and every
  // same-origin iframe's document (a cross-origin one cannot be read, by design). Bounded.
  const ROOTS = (() => {
    const roots = [document];
    for (let i = 0; i < roots.length && roots.length < 64; i++) {
      let all = [];
      try { all = roots[i].querySelectorAll('*'); } catch (e) { continue; }
      for (const el of all) {
        if (roots.length >= 64) break;
        if (el.shadowRoot) roots.push(el.shadowRoot);
        if (el.tagName === 'IFRAME') {
          try { const doc = el.contentDocument; if (doc && doc.documentElement) roots.push(doc); } catch (e) { /* cross-origin */ }
        }
      }
    }
    return roots;
  })();
  const deepAll = (selector) => {
    const out = [];
    for (const root of ROOTS) { try { out.push(...root.querySelectorAll(selector)); } catch (e) { /* bad selector */ } }
    return out;
  };
```
and in the class loop replace `try { nodes = Array.from(document.querySelectorAll(selector)); } catch (e) { nodes = []; }` with `nodes = deepAll(selector);`.

- [ ] **Step 4: The state pass finds a probe in any frame, and forces states on it** — in `capture/states.py` add `import json` and replace `_force` (lines 361-363) with:

```python
#: Finds a probed element wherever GEOMETRY_JS found it — the document, an open shadow root, a
#: same-origin iframe — for CDP, whose DOM.querySelector stops at shadow and frame boundaries.
_DEEP_FIND_JS = r"""
(() => {
  const selector = %s;
  const roots = [document];
  for (let i = 0; i < roots.length && roots.length < 64; i++) {
    const hit = roots[i].querySelector(selector);
    if (hit) return hit;
    for (const el of roots[i].querySelectorAll('*')) {
      if (el.shadowRoot) roots.push(el.shadowRoot);
      if (el.tagName === 'IFRAME') { try { const d = el.contentDocument; if (d) roots.push(d); } catch (e) {} }
    }
  }
  return null;
})()
"""


async def _probe_handle(page: Any, idx: int) -> Any:
    """The probed element's handle, in whichever frame holds it (Playwright's CSS engine pierces open
    shadow roots within a frame)."""
    selector = f'[data-lumen-probe="{idx}"]'
    for frame in page.frames:
        handle = await frame.query_selector(selector)
        if handle is not None:
            return handle
    return await page.locator(selector).element_handle(timeout=HOVER_TIMEOUT_MS)


async def _node_id(cdp: Any, idx: int) -> int:
    found = await cdp.send("Runtime.evaluate", {"expression": _DEEP_FIND_JS % json.dumps(f'[data-lumen-probe="{idx}"]')})
    object_id = (found.get("result") or {}).get("objectId")
    if not object_id:
        raise LookupError(f"probe {idx} not found for a forced state")
    return (await cdp.send("DOM.requestNode", {"objectId": object_id}))["nodeId"]


async def _force(cdp: Any, idx: int, classes: list[str]) -> None:
    await cdp.send("CSS.forcePseudoState", {"nodeId": await _node_id(cdp, idx), "forcedPseudoClasses": classes})
```

In `_probe_one`:
- the first line becomes `handle = await _probe_handle(page, idx)`;
- every `_force(cdp, root, idx, …)` becomes `_force(cdp, idx, …)`;
- the pressed/focus block (`if cdp is not None:` … through the focus `_force(cdp, idx, [])`) is wrapped so a probe CDP cannot reach loses only those two states:

```python
        if cdp is not None:
            try:
                _in_time(deadline)
                await _force(cdp, idx, ["hover", "active"])
                record["pressed"] = look_delta(rest, await _look(handle))
                await _force(cdp, idx, [])
                await _pointer_away(page, handle)
                _in_time(deadline)
                await _force(cdp, idx, ["focus", "focus-visible"])
                record["focus"] = look_delta(rest, await _look(handle))
                await _force(cdp, idx, [])
            except LookupError:
                pass  # a probe CDP cannot reach keeps its rest and hover reads
```
`_probe_one`'s `root` parameter and `probe_states`' `root` variable become unused. Remove them from the signature and the call. Keep `DOM.getDocument` in `probe_states` (`DOM.requestNode` needs the document requested), and change it to `{"depth": -1, "pierce": True}` so shadow and frame nodes are tracked.

- [ ] **Step 5: Run the tests**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`, then `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_style_states.py` (its forced-hover cases, e.g. `b-covered` `how == "forced"`, exercise `_force` on the main document).
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py subsystems/clue-design/apps/api/lumen_ingestion/capture/states.py subsystems/clue-design/apps/api/tests/test_capture_fidelity.py
git commit -m "capture: buttons inside web components and same-origin iframes are measured, with their states"
```

---

## Task 8: Every animation is kept, quoted names match, stylesheets are read once (S6-9, S6-11)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py:1101-1137` (`_first`, `measured_motion`) and the JS name cap (`cs.animationName.slice(0, 120)` → `240`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/motion.py:103-146` (`keyframe_steps`, `attach_keyframes`)
- Test: `subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`, `subsystems/clue-design/apps/api/tests/test_ingestion_measured_styles.py`

**Interfaces:**
- Produces: `geometry._items(value) -> list[str]`, `geometry.MAX_ANIMATIONS = 12`, `motion.css_name(raw) -> str`, `motion._keyframes_index(stylesheets, names) -> dict[str, list]`, `motion._steps(content) -> list[KeyframeStep]`. `keyframe_steps(stylesheets, name)` keeps its signature.
- Fact this task relies on (seen in the review's recorded run): Chromium reports an animation named by a CSS string, `animation: "glow pulse" …`, as the escaped identifier `glow\ pulse`, not with quotes. The `@keyframes "glow pulse"` prelude serialises as `"glow pulse"`. Both sides must be brought to the same name.

- [ ] **Step 1: Write the failing tests** — append to `test_capture_fidelity.py`:

```python
@pytest.mark.parametrize("engine", ENGINES)
def test_s6_9_both_animations_of_an_element_and_a_quoted_name_are_kept(engine: str) -> None:
    run = _run(engine, "shadow_iframe_anim.html")
    kept = {a.name: len(a.frames) for a in run["motion"].animations}
    assert kept.get("rise", 0) >= 2 and kept.get("float", 0) >= 2, kept
    assert kept.get("glow pulse", 0) >= 2, kept
```

Append to `test_ingestion_measured_styles.py`:

```python
def test_s6_11_each_stylesheet_is_parsed_once_whatever_the_number_of_animations(monkeypatch) -> None:
    import tinycss2

    from lumen_ingestion.capture import motion as motion_module
    from lumen_ingestion.evidence import EvidencePointer, MeasuredAnimation, MotionEvidence

    names = ["spin", "ping", "pulse", "bounce", "fade", "slide"]
    css = "".join(f"@keyframes {n}{{from{{opacity:0}}to{{opacity:1}}}}" for n in names)
    sheets = [_sheet(css), _sheet(css + ".x{color:red}")]
    calls = []
    real = tinycss2.parse_stylesheet
    monkeypatch.setattr(motion_module.tinycss2, "parse_stylesheet", lambda *a, **k: calls.append(1) or real(*a, **k))
    pointer = EvidencePointer(source="website", locator="https://x.test/ :: animation")
    kept = motion_module.attach_keyframes(
        MotionEvidence(animations=[MeasuredAnimation(name=n, duration_ms=500, pointer=pointer) for n in names]), sheets)
    assert len(kept.animations) == 6
    assert len(calls) == 2
```
and, in the same file:

```python
@pytest.mark.parametrize("raw, name", [
    ('"glow pulse"', "glow pulse"), ("'glow pulse'", "glow pulse"), ("glow\\ pulse", "glow pulse"),
    ("fade\\31 ", "fade1"), ("spin", "spin"),
])
def test_s6_9_a_keyframes_name_is_read_as_the_cascade_means_it(raw: str, name: str) -> None:
    from lumen_ingestion.capture.motion import css_name

    assert css_name(raw) == name
```
(`_sheet` is the helper that file already uses for `keyframe_steps` tests; import `pytest` if the file lacks it.)

- [ ] **Step 2: Run to verify they fail**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_fidelity.py -k s6_9` and `KEYLESS subsystems/clue-design/apps/api/tests/test_ingestion_measured_styles.py -k s6_11`
Expected: FAIL. `float` and `glow pulse` are missing, and `parse_stylesheet` runs 12 times.

- [ ] **Step 3: Animations, every entry** — in `geometry.py`, replace `_first` and `measured_motion`'s animation loop (lines 1101-1137) with:

```python
#: The most animations a capture keeps (MeasuredComponents@1 holds at most 12 animation tokens).
MAX_ANIMATIONS = 12


def _items(value: object) -> list[str]:
    """Every entry of a computed comma list (`"pulse, spin"` → `["pulse", "spin"]`), parentheses kept."""
    text, depth, start, out = str(value or ""), 0, 0, []
    for index, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(text[start:index].strip())
            start = index + 1
    out.append(text[start:].strip())
    return [item for item in out if item] or [""]


def _first(value: object) -> str:
    """The first entry of a computed comma list (`"pulse, spin"` → `"pulse"`), parentheses kept."""
    return _items(value)[0]
```
(and `css_name` joins the existing `from .motion import clean_icon_svg` import.)

and the loop in `measured_motion`:

```python
    animations: list[MeasuredAnimation] = []
    seen: dict[tuple, MeasuredAnimation] = {}
    for entry in _list(raw.get("animations")):
        if not isinstance(entry, dict):
            continue
        lists = {key: _items(entry.get(key)) for key in ("duration", "easing", "delay", "iterations", "direction", "fill")}
        count = max(1, int(_float(entry.get("count")) or 1))
        for i, raw_name in enumerate(_items(entry.get("name"))):
            name = css_name(raw_name)[:120]
            if not name or name == "none":
                continue
            at = lambda key: lists[key][i % len(lists[key])]  # noqa: E731 — CSS repeats a shorter list
            animation = MeasuredAnimation(
                name=name, duration_ms=_ms(at("duration")), easing=at("easing") or "ease",
                delay_ms=_ms(at("delay")), iterations=at("iterations") or "1",
                direction=at("direction") or "normal", fill_mode=at("fill") or "none",
                count=count, where=str(entry.get("where") or "")[:120],
                pointer=_pointer(url, f"animation {name}"),
            )
            key = (animation.name, animation.duration_ms, animation.easing, animation.iterations, animation.direction)
            if key in seen:
                seen[key].count += count
                continue
            if len(animations) >= MAX_ANIMATIONS:
                continue
            seen[key] = animation
            animations.append(animation)
```
(If `MeasuredAnimation` is frozen, so `count +=` fails, rebuild the stored one with `model_copy(update={"count": …})` and replace it in both `seen` and `animations`.) In `GEOMETRY_JS`'s animation collection, `name: cs.animationName.slice(0, 120)` becomes `name: cs.animationName.slice(0, 240)`.

- [ ] **Step 4: Read each stylesheet once** — in `motion.py`, add `css_name` and make `_keyframes_rules` yield through it:

```python
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\n]?|(.))", re.DOTALL)


def css_name(raw: str) -> str:
    """A keyframes name as the cascade means it (S6-9): the quotes off a name written as a CSS string
    (`"glow pulse"`), the escapes resolved in one written as an identifier — Chromium reports a
    string-named animation as `glow\\ pulse`."""
    text = str(raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return _CSS_ESCAPE.sub(lambda m: chr(min(int(m.group(1), 16), 0x10FFFF)) if m.group(1) else m.group(2), text)
```
In `_keyframes_rules`, `yield tinycss2.serialize(rule.prelude).strip().strip("\"'"), rule.content` becomes `yield css_name(tinycss2.serialize(rule.prelude)), rule.content`.

Then replace `keyframe_steps` and `attach_keyframes` with:

```python
def _keyframes_index(stylesheets: Iterable[Any], names: set[str]) -> dict[str, list]:
    """The last `@keyframes <name>` in cascade order for each wanted name; each sheet that holds any
    keyframes parsed once, however many animations are wanted (S6-11)."""
    found: dict[str, list] = {}
    for sheet in stylesheets:
        text = getattr(sheet, "text", "") or ""
        if not names or "keyframes" not in text.lower():
            continue
        parsed = tinycss2.parse_stylesheet(text, skip_comments=True, skip_whitespace=True)
        for rule_name, content in _keyframes_rules(parsed):
            if rule_name in names:
                found[rule_name] = content
    return found


def _steps(found: list | None) -> list[KeyframeStep]:
    """One `@keyframes` body as clean steps; `[]` when absent or unusable."""
    if found is None:
        return []
    steps: dict[float, dict[str, str]] = {}
    for rule in tinycss2.parse_rule_list(found, skip_comments=True, skip_whitespace=True):
        if getattr(rule, "type", "") != "qualified-rule":
            continue
        declarations: dict[str, str] = {}
        for decl in tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True):
            if getattr(decl, "type", "") != "declaration":
                continue
            value = tinycss2.serialize(decl.value).strip()
            if decl.lower_name in KEYFRAME_PROPERTIES and safe_style_value(value):
                declarations[decl.lower_name] = value
        if not declarations:
            continue
        for offset in _offsets(rule.prelude):
            steps.setdefault(offset, {}).update(declarations)
    ordered = [
        KeyframeStep(offset=offset, declarations=dict(list(decls.items())[:MAX_KEYFRAME_DECLARATIONS]))
        for offset, decls in sorted(steps.items())
    ]
    return ordered if 2 <= len(ordered) <= MAX_KEYFRAME_STEPS else []


def keyframe_steps(stylesheets: Iterable[Any], name: str) -> list[KeyframeStep]:
    """The last `@keyframes <name>` in cascade order, as clean steps; `[]` when absent or unusable."""
    return _steps(_keyframes_index(stylesheets, {name}).get(name))


def attach_keyframes(motion: MotionEvidence, stylesheets: Iterable[Any]) -> MotionEvidence:
    """The animations whose definition the capture holds, with it; the rest are dropped."""
    index = _keyframes_index(list(stylesheets), {animation.name for animation in motion.animations})
    kept = []
    for animation in motion.animations:
        steps = _steps(index.get(animation.name))
        if steps:
            kept.append(animation.model_copy(update={"frames": steps}))
    return motion.model_copy(update={"animations": kept})
```
(`_steps`'s body is the old `keyframe_steps` body after its `found` lookup, unchanged.)

- [ ] **Step 5: Run the tests**

Run with KEYLESS: `test_capture_fidelity.py`, `test_ingestion_measured_styles.py`, `test_ingestion_component_tokens.py`.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py subsystems/clue-design/apps/api/lumen_ingestion/capture/motion.py subsystems/clue-design/apps/api/tests/test_capture_fidelity.py subsystems/clue-design/apps/api/tests/test_ingestion_measured_styles.py
git commit -m "capture: every animation of an element is kept, quoted names match, and stylesheets are parsed once"
```

---

## Task 9: Reveals are re-found by reference, not by position (S6-6)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/states.py:228-276` (`REVEAL_BEFORE_JS`, `REVEAL_AFTER_JS`)
- Test: `subsystems/clue-design/apps/api/tests/test_capture_fidelity.py`

**Interfaces:**
- Produces: `REVEAL_BEFORE_JS` items carry `ref: number` (an index into a page-held list) instead of `path`; `REVEAL_AFTER_JS(items)` reads them by `ref`.

- [ ] **Step 1: Write the failing test** — append to `test_capture_fidelity.py`:

```python
@pytest.mark.parametrize("engine", ENGINES)
def test_s6_6_a_reveal_behind_a_removed_cookie_wall_is_read_from_its_own_element(engine: str) -> None:
    from lumen_ingestion.capture.rendered import _harvest_page

    async def harvest() -> dict:
        if engine == "patchright":
            from patchright.async_api import async_playwright
        else:
            from playwright.async_api import async_playwright
        diagnostics: list[dict] = []
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(headless=True)
            except Exception as error:  # noqa: BLE001
                pytest.skip(f"{engine} chromium unavailable: {error}")
            try:
                page = await browser.new_page(viewport={"width": 1440, "height": 900})
                await page.goto((FIXTURES / "overlay_reveal.html").as_uri())
                result = await _harvest_page(page, diagnostics, measure_states=True)
            finally:
                await browser.close()
        return {"harvest": result, "diagnostics": diagnostics}

    run = asyncio.run(harvest())
    reveals = run["harvest"]["geometry"]["states"]["reveals"]
    assert "LUMI0530" in [d["code"] for d in run["diagnostics"]]   # the wall was removed
    assert any(r["where"].startswith("section#rv") and r["kind"] == "css" for r in reveals), reveals
    assert not any(r["where"].startswith("section#foot3") for r in reveals), reveals
```

- [ ] **Step 2: Run to verify it fails**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_capture_fidelity.py -k s6_6`
Expected: FAIL (the reveal is recorded against `section#foot3`).

- [ ] **Step 3: Hold the elements, not their positions** — in `REVEAL_BEFORE_JS`:
- delete `pathOf`;
- before the loop add `const held = []; window[Symbol.for('lumen.reveal')] = held;`;
- replace `const path = pathOf(el); if (!path) continue;` and the `out.push({ el, path, …` line with:

```js
    held.push(el);
    out.push({ el, ref: held.length - 1, tag: el.tagName.toLowerCase(), opacity: parseFloat(cs.opacity), transform: cs.transform,
      classes: (el.getAttribute('class') || '').slice(0, 240) });
```
Update its leading comment: "Read-only; each element is held in a page-side list (never the DOM) and re-found by its place in that list, so an overlay removed in between cannot shift it (S6-6)."

In `REVEAL_AFTER_JS`, replace the path walk:

```js
  const held = window[Symbol.for('lumen.reveal')] || [];
  return items.map((item) => {
    const node = held[item.ref];
    if (!node || !node.isConnected) return null;
```
(The rest of the mapping is unchanged.) `_reveals` already skips a `None` entry and pairs by position in the two lists, which stay aligned.

- [ ] **Step 4: Run the tests**

Run with KEYLESS: `test_capture_fidelity.py`, `test_capture_style_states.py` (its reveal fixtures `entrance_ctas.html`, `reversed_entrance.html` go through the same two scripts).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/capture/states.py subsystems/clue-design/apps/api/tests/test_capture_fidelity.py
git commit -m "capture: a reveal is re-read from its own element, so a removed cookie wall cannot shift it"
```

---

## Task 10: Minting — truthful names, a short source address, the engine's number rule (S6-4, S6-5, S6-12)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/component_tokens.py:443-472` (`_mint_style`), `:512-518` (`_iterations_ok`), `:635` (`page`)
- Test: `subsystems/clue-design/apps/api/tests/test_ingestion_component_tokens.py`
- Regenerate: the site-kit fixture kits (`scripts/build_site_kit_brand_fixtures.py`)

**Interfaces:**
- Produces: `component_tokens._within_style_names(base: str, asked: list[tuple[str, str, str, dict]]) -> dict[str, str]` mapping each asked path to the path it is minted under. `component_tokens._source_page(locator: str) -> str`.

- [ ] **Step 1: Write the failing tests** — append to `test_ingestion_component_tokens.py`:

```python
def _style(**changes):
    from lumen_ingestion.evidence import EvidencePointer, MeasuredStyle, StyleLook

    pointer = EvidencePointer(source="website", locator="https://x.test/?utm_source=a&gclid=" + "C" * 420 + " :: button solid.7c4cff")
    rest = StyleLook(background="#7C4CFF", color="#FFFFFF", padding=[10.0, 24.0, 10.0, 24.0], radius=[8.0] * 4)
    base = dict(surface="button", variant="solid.7c4cff", count=1, probed="pointer", rest=rest,
                hover=StyleLook(background="#5A2FD6"), pressed=StyleLook(background="#5A2FD6"), pointer=pointer)
    return MeasuredStyle(**{**base, **changes})


def test_s6_4_a_value_used_twice_in_one_style_is_named_after_what_its_places_share() -> None:
    kit = json.loads(GARNER.read_text())
    recipe = next(r for r in mint_component_tokens(kit, [_style()], MotionEvidence()).section["styles"])
    hover, pressed = recipe["states"]["hover"]["fill"], recipe["states"]["pressed"]["fill"]
    assert hover == pressed == "button.solid-7c4cff.hover-pressed.fill", recipe["states"]
    rest = recipe["rest"]
    assert rest["padding-left"] == rest["padding-right"] and rest["padding-top"] == rest["padding-bottom"], rest
    for slot in ("padding-left", "padding-top"):
        assert not any(side in rest[slot] for side in ("right", "top", "bottom", "left")), rest


def test_s6_5_a_long_tracking_address_keeps_every_measured_style() -> None:
    from lumen_ingestion.measured_components import validate_measured_components
    from lumen_ingestion.brief import kit_token_names

    kit = json.loads(GARNER.read_text())
    section = mint_component_tokens(kit, [_style()], MotionEvidence()).section
    assert section["source"] == "website:https://x.test/", section["source"]
    validate_measured_components(section, token_names=kit_token_names(kit))


@pytest.mark.parametrize("value, ok", [
    ("1", True), ("2.5", True), (".5", True), ("5.", True), ("1e3", True), ("infinite", True), ("+5", True),
    ("1_000", False), ("٥", False), ("５", False), (" 5", False), ("5 ", False), ("inf", False), ("nan", False),
    ("0", False), ("1000.0000001", False),
])
def test_s6_12_iteration_counts_follow_the_engines_own_number_rule(value: str, ok: bool) -> None:
    from lumen_ingestion.normalizer.component_tokens import _iterations_ok

    assert _iterations_ok(value) is ok
```
(`GARNER`, `json`, `mint_component_tokens`, `MotionEvidence` are already imported in that file. If one is missing, import it at the top.) Also extend the existing parity test `test_ingestion_and_the_engine_agree_on_every_style_value` (line ~302) with iteration values `"1_000"`, `"٥"`, `"５"`, `"+5"`, `".5"`, `"5."` in whatever animation-token form that test already builds. The engine is the oracle there.

- [ ] **Step 2: Run to verify they fail**

Run: `KEYLESS subsystems/clue-design/apps/api/tests/test_ingestion_component_tokens.py -k "s6_4 or s6_5 or s6_12"`
Expected: FAIL. Pressed fill is named `…hover.fill`; the source is >400 characters; `1_000`/`٥`/`５` pass Python.

- [ ] **Step 3: S6-12 — the engine's grammar** (`f64::from_str`: ASCII sign, digits, optional point, optional exponent; no spaces, no underscores, no other digits):

```python
_RUST_FLOAT = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)


def _iterations_ok(value: str) -> bool:
    """An iteration count the engine accepts (`brand.rs` `iterations_ok`): `infinite`, or a number in
    Rust's own float spelling — finite, above 0, at most 1000 (S6-12: `float()` also accepts `1_000`,
    padding and non-ASCII digits, which the engine refuses and which would fail the whole kit)."""
    if value == "infinite":
        return True
    if not _RUST_FLOAT.fullmatch(value):
        return False
    number = float(value)
    return math.isfinite(number) and 0 < number <= 1000
```
(`import math` if the module lacks it.)

- [ ] **Step 4: S6-5 — the source address is the page, not its tracking** — add:

```python
def _source_page(locator: str) -> str:
    """The page a measurement came from, as `scheme://host/path` (S6-5): a pasted homepage address
    with UTM or gclid parameters runs past MeasuredComponents@1's 400-character limit and would drop
    every measured style; the query and fragment name the visit, not the page. A path still too long
    leaves the host alone."""
    parts = urlsplit(locator.split(" :: ", 1)[0])
    page = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))
    return page if len(page) <= 392 else urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
```
(`from urllib.parse import urlsplit, urlunsplit`.) Line 635 becomes `page = _source_page(pointers[0].locator) if pointers else ""`.

- [ ] **Step 5: S6-4 — a value shared inside one style gets a name its places share** — add:

```python
def _within_style_names(base: str, asked: list[tuple[str, str, str, dict]]) -> dict[str, str]:
    """`{asked path: path to mint under}` for one style (S6-4). A value asked for in two or more places
    of this style is named after what those places share — the states joined (`hover-pressed`,
    omitted when all at rest), then the slot when they share it, else its kind (`padding` for
    padding-left and padding-right) — instead of after whichever place asked first. Each entry of
    `asked` is `(state or "", slot, group, value)`; places of one value with different kinds are
    left alone."""
    groups: list[tuple[str, dict, list[tuple[str, str]]]] = []
    for state, slot, group, value in asked:
        bucket = next((places for g, v, places in groups if g == group and _same(group, v, value)), None)
        if bucket is None:
            groups.append((group, value, [(state, slot)]))
        else:
            bucket.append((state, slot))
    out: dict[str, str] = {}
    for _group, _value, places in groups:
        if len(places) < 2 or len({_slot_kind(slot) for _, slot in places}) != 1:
            continue
        states = [s for s in ("", *STATES) if s in {state for state, _ in places}]
        state_part = "-".join(s or "rest" for s in states) if states != [""] else ""
        slots = {slot for _, slot in places}
        slot_part = slots.pop() if len(slots) == 1 else _slot_kind(places[0][1])
        neutral = f"{base}.{state_part + '.' if state_part else ''}{slot_part}"
        for state, slot in places:
            out[f"{base}.{state + '.' if state else ''}{slot}"] = neutral
    return out
```

and restructure `_mint_style`'s rest and state loops (lines 452-472) so it first lists what it will ask, then names it:

```python
    asked: list[tuple[str, str, str, dict]] = [("", slot, group, value) for slot, group, value in _slots(style.rest, at_rest=True, fonts=fonts)]
    for state in STATES:
        look = getattr(style, state)
        if look is None:
            continue
        pairs = [s for s in _slots(look, at_rest=False, fonts=fonts) if s[0] != "font"]
        font = _state_font(style.rest, look, fonts)
        if font:
            pairs.append(("font", "typography", font))
        asked.extend((state, slot, group, value) for slot, group, value in pairs)
    names = _within_style_names(base, asked)
    for state, slot, group, value in asked:
        path = f"{base}.{state + '.' if state else ''}{slot}"
        token = m.name(names.get(path, path), group, value,
                       pointer=f"{where} {state or 'rest'} {slot}", slot=slot)
        if not token:
            continue
        if state:
            recipe["states"].setdefault(state, {})[slot] = token
        else:
            recipe["rest"][slot] = token
    focus = style.focus
    if focus is not None and focus.browser_focus_ring:
        recipe["browser_focus_ring"] = True
```
(Cross-style shared values keep precedence: `m.name` still renames any value two styles ask for to `…shared-<key>.<kind>`, because `_shared_values` sees the same `_Requests` paths as before. `_Requests.name` records the path it is given, so in `_shared_values` the neutral name stands in for the place it replaces. Both have the same component and kind, which is all `_shared_values` keys on. Keep a `recipe["states"][state]` entry only when it has at least one slot, as before. `setdefault` only creates it when a token was minted.)

- [ ] **Step 6: Regenerate the site-kit fixture kits and run the minting suites**

```bash
cd subsystems/clue-design && PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python scripts/build_site_kit_brand_fixtures.py && git status --short ../../apps/frontend
```
Then run with KEYLESS: `test_ingestion_component_tokens.py`, `test_measured_components.py`, `test_ingestion_measured_styles.py`, `test_ingestion_section_mint.py`. Then the site-kit package (`cd apps/frontend/packages/site-kit && npm test`) and the Brand page model tests (`cd apps/frontend && npx tsx --test src/features/brand-context/model/*.test.ts`).
Expected: all pass. A site-kit test that named a misleading token (`…padding-right` for left padding, `…hover.fill` for pressed) should be updated to the new name. Record each rename in the commit message body.

- [ ] **Step 7: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/normalizer/component_tokens.py subsystems/clue-design/apps/api/tests/test_ingestion_component_tokens.py subsystems/clue-design/scripts apps/frontend/packages/site-kit/test/fixtures apps/frontend/src/features/brand-context
git commit -m "ingestion: style tokens are named after the places that share them, tracking parameters never drop measured styles, iteration counts use the engine's number rule"
```

---

## Task 11: Whole-branch gates and the record

**Files:**
- Modify: `docs/superpowers/verification/2026-10-14-wave2-area-review-findings.md` (§S6 statuses, §4.6 status, §2 counts)
- Modify: `_memory/2026-10-15-publishing-live-sites.md` (append), or create `_memory/2026-10-16-brand-capture-fidelity.md`

- [ ] **Step 1: Python gates.** Run, each with KEYLESS, one file at a time: every test file touched above, plus `test_a9_scenarios.py` (end to end through the API with real capture). Never the whole design suite synchronously. If a full run is wanted, start it in the background and record it as owed.

- [ ] **Step 2: Frontend gates** (lane stack down for the build):

```bash
cd apps/frontend/packages/site-kit && npm test && npm run typecheck && npm run build
cd ../site-editor && npm test
cd ../.. && npm run design-system:build && npm run lint && npm run build
```
Expected: all green.

- [ ] **Step 3: Mark the findings.** In the review document, set each of S6-1, S6-2 (colour half), S6-3, S6-4, S6-5, S6-6, S6-7, S6-8, S6-9, S6-10, S6-11, S6-12 to `**fixed** 2026-10-16 (<commit>)`, and §4.6's status to fixed. Note walk defect 4 as fixed in the memory note.

- [ ] **Step 4: Record in `_memory/`**: what changed, the LUMI0609 code, that existing kits are fixed on screen by Task 1 but keep their stored values until re-captured, and the owed re-capture (Task 12).

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/verification/2026-10-14-wave2-area-review-findings.md _memory
git commit -m "record: brand capture fidelity findings fixed; re-capture of existing brands owed"
```

---

## Task 12: Re-capture the live brands (founder-gated — do not run without an explicit yes)

Tasks 1–11 fix what every existing site shows. A re-capture is what puts the measured values into
existing kits: true band text, oklch colours, icon paint and the new names.

- [ ] **Step 1: Ask, in chat, with a measured estimate.** Read how long each brand's last website ingestion took, read-only, from the lane DB: the `design_ingestion_job` row's created and finished timestamps for that brand kit. Name each brand (Garner Health, Conduit, Clue) with its measured time. Say that a re-capture also runs the model description steps, which spend model credit; that it publishes a new kit version; and that documents keep their pinned version until moved. Wait for an explicit yes per brand.

- [ ] **Step 2: Only after a yes:** run the website ingestion for that brand through the product's normal path (Brand page → re-extract, or `POST /brand-kits/ingest/website`) on the lane stack. Then re-pin the sites that should take the new kit (`POST /documents/{id}/brand-kit`) only if the founder asks.

- [ ] **Step 3: Check each brand in the in-app browser:** section text reads, oklch buttons keep their colours, icons show at the right size and colour, and the published page shows the page colour under short pages and in a dark-mode pane. Report what was checked and anything still wrong.
