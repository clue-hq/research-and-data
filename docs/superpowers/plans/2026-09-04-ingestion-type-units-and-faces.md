# Ingestion: type units and font faces (Editor Quality Plan 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A harvested brand kit carries line-height and letter-spacing as ratios of the element's own size, ships one static face per named weight of a variable font so Bold works, and the editor's Bold/Italic toggles say plainly when the kit has no face to serve them.

**Architecture:** Three small changes at ingestion (the CSS unit parser, a guard in the type-style normalizer, and a variable-font instancing step in the evidence builder that reuses the Google-library instancer), one dry-run backfill script that re-derives stored kits' type units and publishes a new immutable kit version, and one frontend change (a face-availability reader on the CanvasKit registry, threaded into the scene text toolbar as a disabled-with-reason state). No engine (Rust) change. No new dependencies.

**Tech Stack:** Python 3.12 (`lumen_ingestion`, `lumen_api`, fontTools `varLib.instancer`), pytest; TypeScript (Next.js frontend, `design-editor`), node:test / vitest as each file already uses.

**Spec:** `docs/superpowers/plans/2026-09-04-editor-quality-roadmap.md` — Plan 1, items A and B. Evidence: `_memory/2026-09-04-editor-quality-dry-run.md`.

## Global Constraints

- **Ordering (founder, 2026-09-04):** this is Plan 1 of four; Plans 2–4 do not start here. Nothing in this plan touches the inspector toolbar (Plan 4, preview-gated).
- **Implementers are Opus subagents; the controller reviews, verifies first-hand, and decides.** A subagent that hits a decision escalates; it does not choose.
- **Commit locally after every task; never push; no AI attribution in commit messages; never `git stash`.**
- **Python tests run from `subsystems/clue-design`:**
  `set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/<file> -q`
  DB-backed tests (Tasks 4b, 5) run ONLY with `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55040/clue_plan1_test` (the controller creates and migrates it before those tasks). **Never run any design suite against the colombo DSN** — its embedded worker claims test jobs.
- **Frontend runs from `apps/frontend`.** Gate: `npm run design-system:build && npm run lint && npm run build`. Use the runner each test file already imports (`node:test` files run with `npx tsx --test <file>`; `__tests__/*.test.ts` vitest files with `npx vitest run <file>`).
- **Never run the full clue-design suite inline** (it takes over an hour). Focused files only.
- **Diagnostic codes allocated here:** `LUMI0233` type-unit guard (normalizer), `LUMI0234` variable font instanced (info), `LUMI0235` instancing failed (warning). Verify each is unused (`grep -rn LUMI023[345] subsystems/clue-design/apps/api`) before first use.
- **Copy for the disabled toggles (exact):** `No bold face for “<family>” in the brand kit` and `No italic face for “<family>” in the brand kit`.
- Kit versions are immutable rows: every stored-kit change publishes a NEW version through `publish_next_brand_kit_version`.

---

## Verified root causes (do not re-derive)

- `subsystems/clue-design/apps/api/lumen_ingestion/capture/parse.py:767` `_line_height` returns `px / 16.0` for px lengths, and `_letter_spacing` (same file, just below) returns `px / 16.0` too. Both call sites — declared CSS (~line 1130) and rendered samples (~line 1229) — have the element font size beside them. The Apollo kit's stored evidence shows the rendered h1 as `size 72, line_height 4.5, letter_spacing -0.045, weight 550` → the true values are `1.0` and `-0.01`.
- `normalizer/typography.py::build_type_styles` copies `anchor.line_height` / `anchor.letter_spacing` unguarded.
- The Apollo kit (`brand_kit_ing_10c2b0ea17054c668384ae5e91abfebb` v2, workspace `ws_8163898e0d0e4420b578bdbc57d7f3e4`) holds ONE face per family (`soehne` 400, `seasonMix` 400); both stored files are variable fonts (fvar `wght`). The rendered h1 weight 550 was snapped to 400 (LUMI0232) because nothing else was custodied.
- Italic harvest already works: `parse.py::_parse_font_face` keeps `font-style`, `_accumulate_font` appends every face. Apollo declares no italic face. Task 4 pins this with a test; no harvest code is written.
- Editor: `engine/scene/canvaskit/loadCanvasKit.ts` keeps a private `familyFaces` registry; `hasItalicFace(family)` exists; there is no bold equivalent. `components/scene-text-toolbar.logic.ts::sceneTextMarkState` returns `{pressed, disabled}` with no reason; the toolbar (`scene-text-toolbar.tsx` ~line 190) renders `title` from label+shortcut only. `scene-artifact-canvas.tsx` ~line 2427 `applyMark` writes the mark regardless of faces.

---

### Task 1: Element-relative line-height and letter-spacing in the CSS parser

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/parse.py` (`_line_height`, `_letter_spacing`, the declared-CSS loop ~1100–1150, the rendered-sample block ~1220–1235)
- Test: `subsystems/clue-design/apps/api/tests/test_ingestion_type_units.py` (new)

**Interfaces:**
- Produces: `_line_height(value: str, font_size_px: float | None) -> float | None` and `_letter_spacing(value: str, font_size_px: float | None) -> float | None`. Both return a ratio/em of the ELEMENT size. A px/rem length with no element size returns `None`.
- `ParsedType.line_height` / `.letter_spacing` keep their types; only their values change.

- [ ] **Step 1: Write the failing tests**

```python
# subsystems/clue-design/apps/api/tests/test_ingestion_type_units.py
"""Plan 1 item A (2026-09-04): line-height and letter-spacing are ratios of the ELEMENT's font
size, never of the root 16px. The Apollo harvest stored a 72px headline leading as 4.5 (72/16)
and its -0.72px tracking as -0.045; the true values are 1.0 and -0.01."""

from __future__ import annotations

from pathlib import Path

from lumen_ingestion.capture.parse import _letter_spacing, _line_height, parse_site
from lumen_ingestion.capture.snapshot import Stylesheet, load_snapshot

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ingestion" / "snapshots"


def test_line_height_units_resolve_against_the_element_size() -> None:
    assert _line_height("1.1", 64.0) == 1.1
    assert _line_height("1.2em", 64.0) == 1.2
    assert _line_height("120%", 64.0) == 1.2
    assert _line_height("72px", 64.0) == 1.125
    assert _line_height("4.5rem", 64.0) == 1.125  # 4.5 × 16 = 72px, over 64px
    assert _line_height("72px", 72.0) == 1.0  # the Apollo headline
    assert _line_height("normal", 64.0) is None
    assert _line_height("", 64.0) is None


def test_a_length_with_no_element_size_is_an_honest_blank_not_px_over_16() -> None:
    assert _line_height("72px", None) is None
    assert _line_height("4.5rem", None) is None
    assert _line_height("1.1", None) == 1.1  # unitless never needed the size
    assert _letter_spacing("-0.72px", None) is None
    assert _letter_spacing("-0.01em", None) == -0.01


def test_letter_spacing_units_resolve_against_the_element_size() -> None:
    assert _letter_spacing("-0.72px", 72.0) == -0.01  # the Apollo headline
    assert _letter_spacing("-0.01em", 72.0) == -0.01
    assert _letter_spacing("0.5rem", 16.0) == 0.5  # 8px over 16px
    assert _letter_spacing("normal", 72.0) is None


def _with_css_and_samples(css: str, samples: list[dict]):
    snapshot = load_snapshot(FIXTURES / "insight_static.json")
    return snapshot.model_copy(
        update={
            "stylesheets": [Stylesheet(url="https://units.example/site.css", text=css)],
            "computed_samples": samples,
        }
    )


def test_parse_site_declared_px_line_height_uses_the_rule_font_size() -> None:
    css = 'h1{ font-family: "Aeonik"; font-size: 64px; line-height: 72px; letter-spacing: -0.64px; }'
    parsed = parse_site(_with_css_and_samples(css, []))
    h1 = next(t for t in parsed.type_samples if t.label == "h1" and t.size_px == 64.0)
    assert h1.line_height == 1.125
    assert h1.letter_spacing == -0.01


def test_parse_site_declared_px_line_height_before_font_size_still_resolves() -> None:
    # Declaration order must not matter: line-height first, font-size second.
    css = 'h1{ line-height: 72px; font-family: "Aeonik"; font-size: 64px; }'
    parsed = parse_site(_with_css_and_samples(css, []))
    h1 = next(t for t in parsed.type_samples if t.label == "h1" and t.size_px == 64.0)
    assert h1.line_height == 1.125


def test_parse_site_rendered_sample_uses_its_own_font_size() -> None:
    samples = [
        {
            "tag": "h1",
            "area": 50000,
            "fontFamily": "seasonMix",
            "fontSize": "72px",
            "fontWeight": "550",
            "lineHeight": "72px",
            "letterSpacing": "-0.72px",
        }
    ]
    parsed = parse_site(_with_css_and_samples("", samples))
    h1 = next(t for t in parsed.type_samples if t.locator.startswith("rendered ::") and t.label == "h1")
    assert h1.size_px == 72.0
    assert h1.line_height == 1.0
    assert h1.letter_spacing == -0.01
    assert h1.weight == 550
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `subsystems/clue-design`): `set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_ingestion_type_units.py -q`
Expected: FAIL — `_line_height() takes 1 positional argument but 2 were given` (and the parse_site cases with 4.5 / -0.045 values).

- [ ] **Step 3: Replace the two unit helpers**

In `parse.py`, replace `_line_height` and `_letter_spacing` with:

```python
_ROOT_FONT_SIZE_PX = 16.0


def _line_height(value: str, font_size_px: float | None) -> float | None:
    """CSS ``line-height`` as a ratio of the ELEMENT's font size.

    unitless / ``em`` / ``%`` are ratios already; ``px`` divides by the element size; ``rem``
    is root-relative (× 16) and then divides by the element size. A length with no element
    size is unconvertible → ``None`` (an honest blank). It must never fall back to ``px / 16``:
    that was the 2026-09-04 Apollo bug — a 72px headline leading stored as 4.5.
    """
    value = value.strip().lower()
    if not value or value in ("normal", "inherit", "initial", "unset"):
        return None
    try:
        return float(value)
    except ValueError:
        pass
    m = re.match(r"^(-?[\d.]+)(px|rem|em|%)$", value)
    if not m:
        return None
    number, unit = float(m.group(1)), m.group(2)
    if unit == "em":
        return number
    if unit == "%":
        return number / 100.0
    px = number if unit == "px" else number * _ROOT_FONT_SIZE_PX
    if not font_size_px or font_size_px <= 0:
        return None
    return px / font_size_px


def _letter_spacing(value: str, font_size_px: float | None) -> float | None:
    """CSS ``letter-spacing`` in em of the ELEMENT's font size (same rules as ``_line_height``)."""
    value = value.strip().lower()
    if not value or value in ("normal", "inherit", "initial", "unset"):
        return None
    m = re.match(r"^(-?[\d.]+)(px|rem|em)$", value)
    if not m:
        return None
    number, unit = float(m.group(1)), m.group(2)
    if unit == "em":
        return number
    px = number if unit == "px" else number * _ROOT_FONT_SIZE_PX
    if not font_size_px or font_size_px <= 0:
        return None
    return px / font_size_px
```

- [ ] **Step 4: Fix the declared-CSS call site (~line 1107–1135)**

The declaration loop sees `line-height` and `font-size` in whatever order the rule wrote them, so keep the raw strings and resolve AFTER the loop:

```python
        family = None
        size_px = None
        font_weight = None
        line_height_raw: str | None = None
        letter_spacing_raw: str | None = None
        for decl in decls:
            ...
            elif name == "font-size":
                size_px = _px_from_length(value)
            elif name == "font-weight":
                font_weight = _weight_int(value)
            elif name == "line-height":
                line_height_raw = value
            elif name == "letter-spacing":
                letter_spacing_raw = value

        line_height = _line_height(line_height_raw, size_px) if line_height_raw is not None else None
        letter_spacing = (
            _letter_spacing(letter_spacing_raw, size_px) if letter_spacing_raw is not None else None
        )
```

(the `ParsedType(...)` construction below is unchanged).

- [ ] **Step 5: Fix the rendered-sample call site (~line 1220–1235)**

```python
        if label and family:
            size_px = _px_from_length(str(sample.get("fontSize") or ""))
            parsed.type_samples.append(
                ParsedType(
                    label="body" if label == "html" else label,
                    family=_first_family(str(family)),
                    weight=_weight_int(str(sample.get("fontWeight") or "")),
                    size_px=size_px,
                    line_height=_line_height(str(sample.get("lineHeight") or ""), size_px),
                    letter_spacing=_letter_spacing(str(sample.get("letterSpacing") or ""), size_px),
                    locator=locator,
                )
            )
```

- [ ] **Step 6: Find every other caller**

Run: `grep -rn "_line_height(\|_letter_spacing(" subsystems/clue-design/apps/api --include='*.py'`
Expected: only `parse.py` (the two call sites + the definitions) and the new test. If `pdf.py` or another module calls either helper, pass that caller's element size the same way (and report it in the task summary).

- [ ] **Step 7: Run the new tests and the existing parse tests**

Run: `... pytest apps/api/tests/test_ingestion_type_units.py apps/api/tests/test_ingestion_capture.py apps/api/tests/test_ingestion_source_truth_styling.py -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/capture/parse.py subsystems/clue-design/apps/api/tests/test_ingestion_type_units.py
git commit -m "fix(ingestion): line-height and letter-spacing are ratios of the element size, not px/16"
```

---

### Task 2: Type-unit guard in the normalizer (LUMI0233)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/typography.py` (`build_type_styles`, new constants + diagnostic helper)
- Test: `subsystems/clue-design/apps/api/tests/test_ingestion_normalizer.py` (append)

**Interfaces:**
- Produces: `LINE_HEIGHT_RATIO_RANGE: tuple[float, float] = (0.5, 2.5)`, `LETTER_SPACING_EM_LIMIT: float = 0.5`, `type_unit_diagnostic(role: str, field: str, value: float, locator: str) -> dict` (code `LUMI0233`, severity `warning`). Task 5 imports the two constants.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_ingestion_normalizer.py`; use that file's existing imports — it already imports `build_type_styles`/`resolve_anchors` or the evidence models; add what is missing)

```python
def test_a_misparsed_line_height_is_dropped_with_a_diagnostic_naming_the_role() -> None:
    from lumen_ingestion.evidence import BrandEvidence, EvidencePointer, TypeSample
    from lumen_ingestion.normalizer.typography import build_type_styles, resolve_anchors

    evidence = BrandEvidence.model_validate(
        {
            "schema_version": 1,
            "source": {"kind": "website", "url": "https://apollo.example"},
            "type_samples": [
                {
                    "label": "h1", "family": "seasonMix", "weight": 550, "size_px": 72.0,
                    "line_height": 4.5, "letter_spacing": -0.045,
                    "pointer": {"source": "website", "locator": "rendered :: h1"},
                },
                {
                    "label": "body", "family": "soehne", "weight": 400, "size_px": 18.0,
                    "line_height": 1.6875, "letter_spacing": 0.0106,
                    "pointer": {"source": "website", "locator": "rendered :: body"},
                },
            ],
        }
    )
    styles, diagnostics = build_type_styles(resolve_anchors(evidence))
    headline = styles["type.headline"]
    assert headline["line_height"] == 1.1  # the derived default, not 4.5
    assert headline["letter_spacing"] == -0.045  # within the em limit → kept
    assert styles["type.body"]["line_height"] == 1.6875  # a sane anchor is left alone
    codes = [d for d in diagnostics if d["code"] == "LUMI0233"]
    assert len(codes) == 1
    assert "type.headline" in codes[0]["message"] and "4.5" in codes[0]["message"]
    assert "rendered :: h1" in codes[0]["message"]


def test_an_absurd_letter_spacing_is_dropped_the_same_way() -> None:
    from lumen_ingestion.evidence import BrandEvidence
    from lumen_ingestion.normalizer.typography import build_type_styles, resolve_anchors

    evidence = BrandEvidence.model_validate(
        {
            "schema_version": 1,
            "source": {"kind": "website", "url": "https://apollo.example"},
            "type_samples": [
                {
                    "label": "h1", "family": "seasonMix", "weight": 700, "size_px": 72.0,
                    "line_height": 1.0, "letter_spacing": 2.0,
                    "pointer": {"source": "website", "locator": "rendered :: h1"},
                }
            ],
        }
    )
    styles, diagnostics = build_type_styles(resolve_anchors(evidence))
    assert styles["type.headline"]["line_height"] == 1.0
    assert styles["type.headline"]["letter_spacing"] == -0.01  # spec default for headline
    assert [d["code"] for d in diagnostics] == ["LUMI0233"]
```

If `BrandEvidence`'s `source` field has a different required shape, copy the `source` block from `tests/fixtures/ingestion/evidence_minimal.json` instead of the literal above.

- [ ] **Step 2: Run to verify they fail**

Run: `... pytest apps/api/tests/test_ingestion_normalizer.py -q -k "misparsed or absurd"`
Expected: FAIL — headline `line_height == 4.5`, no LUMI0233.

- [ ] **Step 3: Add the guard**

In `typography.py`, near `weight_snap_diagnostic`:

```python
#: A real style's leading, as a ratio of its font size. Outside this band the number is a unit
#: misparse (the 2026-09-04 Apollo kit carried 4.5 = 72px / 16), never a design choice.
LINE_HEIGHT_RATIO_RANGE: tuple[float, float] = (0.5, 2.5)
#: Tracking beyond half an em in either direction is likewise a misparse.
LETTER_SPACING_EM_LIMIT: float = 0.5


def type_unit_diagnostic(role: str, field: str, value: float, locator: str) -> dict:
    """One LUMI0233 warning per (role, field) whose harvested unit could not be a real style."""
    return {
        "code": "LUMI0233",
        "severity": "warning",
        "message": (
            f"type.{role} {field} {value:g} (from {locator}) is outside the range a real style "
            f"can carry; it was a unit misparse, so the role keeps its derived default"
        ),
    }
```

In `build_type_styles`, replace the two anchor copies:

```python
            if anchor.line_height:
                lo, hi = LINE_HEIGHT_RATIO_RANGE
                if lo <= anchor.line_height <= hi:
                    final_lh = anchor.line_height
                else:
                    diagnostics.append(
                        type_unit_diagnostic(role, "line_height", anchor.line_height, anchor.pointer.locator)
                    )
            if anchor.letter_spacing is not None:
                if abs(anchor.letter_spacing) <= LETTER_SPACING_EM_LIMIT:
                    final_ls = anchor.letter_spacing
                else:
                    diagnostics.append(
                        type_unit_diagnostic(role, "letter_spacing", anchor.letter_spacing, anchor.pointer.locator)
                    )
```

(`anchor` is a `TypeSample`; it carries `pointer: EvidencePointer` with `.locator`.)

- [ ] **Step 4: Run the normalizer tests**

Run: `... pytest apps/api/tests/test_ingestion_normalizer.py -q`
Expected: all PASS (the golden snapshots must not change — no fixture carries an out-of-band value; if one does, STOP and report which, do not regenerate goldens).

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/normalizer/typography.py subsystems/clue-design/apps/api/tests/test_ingestion_normalizer.py
git commit -m "fix(ingestion): guard type roles against misparsed line-height/letter-spacing (LUMI0233)"
```

---

### Task 3: Variable-font instancing module + synthetic variable-font fixture

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/capture/font_instances.py`
- Create: `subsystems/clue-design/apps/api/tests/variable_font_fixture.py`
- Test: `subsystems/clue-design/apps/api/tests/test_font_instances.py`

**Interfaces:**
- Consumes: `lumen_ingestion.font_library._instance_bytes(source: bytes, weight: int, family: str, italic: bool = False) -> bytes` (raises `FontLibraryError`), `lumen_api.font_containers.decode_web_font(data) -> DecodedFont | None` (raises `FontContainerError`).
- Produces:
  - `INSTANCE_WEIGHTS: tuple[int, ...] = (400, 500, 600, 700)`
  - `@dataclass(frozen=True) FontInstance(weight: int, italic: bool, data: bytes, sha256: str)`
  - `@dataclass FontInstancePlan(family: str, variable: bool, wght_range: tuple[float, float] | None, instances: list[FontInstance], skipped_weights: list[int], error: str | None)`
  - `plan_font_instances(family: str, data: bytes, *, italic: bool = False, weights: tuple[int, ...] = INSTANCE_WEIGHTS) -> FontInstancePlan`
  - Fixture: `build_variable_font(family: str = "Synthetic VF", wght: tuple[int, int] = (300, 900)) -> bytes` (a TTF with an `fvar` `wght` axis), and `as_woff2(data: bytes) -> bytes`.

- [ ] **Step 1: Write the synthetic variable-font fixture**

```python
# subsystems/clue-design/apps/api/tests/variable_font_fixture.py
"""A tiny variable TTF built in memory (no licensed bytes in the repo): one axis ``wght``,
two masters (a thin and a heavy stem on the glyph ``I``). Enough for fontTools' instancer and
for the OS/2 checks the ingestion tests make."""

from __future__ import annotations

from io import BytesIO

from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, SourceDescriptor
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.varLib import build as build_variable


def _master(family: str, stem: int) -> TTFont:
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "space", "I"])
    fb.setupCharacterMap({0x20: "space", 0x49: "I"})
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((100 + stem, 0))
    pen.lineTo((100 + stem, 700))
    pen.lineTo((100, 700))
    pen.closePath()
    empty = TTGlyphPen(None).glyph()
    fb.setupGlyf({".notdef": empty, "space": empty, "I": pen.glyph()})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "space": (250, 0), "I": (200 + stem, 100)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(
        sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200,
        usWeightClass=400, achVendID="TEST",
    )
    fb.setupPost()
    return fb.font


def build_variable_font(family: str = "Synthetic VF", wght: tuple[int, int] = (300, 900)) -> bytes:
    doc = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.name, axis.tag = "Weight", "wght"
    axis.minimum, axis.default, axis.maximum = wght[0], wght[0], wght[1]
    doc.addAxis(axis)
    for location, stem in ((wght[0], 60), (wght[1], 200)):
        source = SourceDescriptor()
        source.font = _master(family, stem)
        source.location = {"Weight": location}
        doc.addSource(source)
    font, _model, _masters = build_variable(doc)
    out = BytesIO()
    font.save(out)
    return out.getvalue()


def as_woff2(data: bytes) -> bytes:
    font = TTFont(BytesIO(data), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = "woff2"
    out = BytesIO()
    font.save(out)
    return out.getvalue()
```

Sanity-run it before writing tests: `... ../../.venv/bin/python -c "import sys; sys.path.insert(0,'apps/api/tests'); from variable_font_fixture import build_variable_font; from fontTools.ttLib import TTFont; from io import BytesIO; f=TTFont(BytesIO(build_variable_font())); print([a.axisTag for a in f['fvar'].axes], 'gvar' in f)"` → expected `['wght'] True`. If `build_variable` rejects the in-memory sources, set `source.path = None` and `source.filename = None` explicitly, or write the masters to `tmp` — report which was needed.

- [ ] **Step 2: Write the failing tests**

```python
# subsystems/clue-design/apps/api/tests/test_font_instances.py
"""Plan 1 item B (2026-09-04): a harvested VARIABLE font is instanced into one static face per
named weight, so the kit (and the editor's Bold) has real faces to serve."""

from __future__ import annotations

from io import BytesIO

from fontTools.ttLib import TTFont

from lumen_ingestion.capture.font_instances import INSTANCE_WEIGHTS, plan_font_instances
from variable_font_fixture import as_woff2, build_variable_font

INTER = __import__("pathlib").Path(__file__).resolve().parents[3] / "fonts" / "Inter-Regular.ttf"


def _os2_weight(data: bytes) -> int:
    return TTFont(BytesIO(data))["OS/2"].usWeightClass


def test_a_variable_font_yields_one_static_face_per_named_weight() -> None:
    plan = plan_font_instances("Synthetic VF", build_variable_font())
    assert plan.variable is True
    assert plan.wght_range == (300.0, 900.0)
    assert plan.error is None
    assert [i.weight for i in plan.instances] == list(INSTANCE_WEIGHTS)
    assert [_os2_weight(i.data) for i in plan.instances] == [400, 500, 600, 700]
    assert all(i.italic is False for i in plan.instances)
    # Static: the instance carries no fvar, and its digest names the exact bytes.
    first = plan.instances[0]
    assert "fvar" not in TTFont(BytesIO(first.data))
    assert first.sha256 == __import__("hashlib").sha256(first.data).hexdigest()
    # The 700 instance is a real Bold: heavier advance than the 400 one (the stem grew).
    widths = {i.weight: TTFont(BytesIO(i.data))["hmtx"]["I"][0] for i in plan.instances}
    assert widths[700] > widths[400]


def test_a_woff2_wrapped_variable_font_is_decoded_before_instancing() -> None:
    plan = plan_font_instances("Synthetic VF", as_woff2(build_variable_font()))
    assert plan.variable is True and len(plan.instances) == 4
    assert plan.instances[0].data[:4] == b"\x00\x01\x00\x00"  # sfnt, never woff2


def test_weights_outside_the_axis_range_are_skipped_not_fabricated() -> None:
    plan = plan_font_instances("Narrow VF", build_variable_font(wght=(500, 700)))
    assert [i.weight for i in plan.instances] == [500, 600, 700]
    assert plan.skipped_weights == [400]
    assert plan.error is None


def test_a_static_font_is_left_alone() -> None:
    plan = plan_font_instances("Inter", INTER.read_bytes())
    assert plan.variable is False
    assert plan.instances == [] and plan.error is None


def test_garbage_bytes_report_an_error_instead_of_raising() -> None:
    plan = plan_font_instances("Junk", b"wOF2" + b"\x00" * 64)
    assert plan.variable is False and plan.instances == []
    assert plan.error  # the decode failure, in words


def test_italic_instances_carry_the_italic_bit() -> None:
    plan = plan_font_instances("Synthetic VF", build_variable_font(), italic=True)
    assert all(i.italic for i in plan.instances)
    assert TTFont(BytesIO(plan.instances[0].data))["OS/2"].fsSelection & 0x0001
```

- [ ] **Step 3: Run to verify they fail**

Run: `... pytest apps/api/tests/test_font_instances.py -q`
Expected: FAIL — `ModuleNotFoundError: lumen_ingestion.capture.font_instances`.

- [ ] **Step 4: Write the module**

```python
# subsystems/clue-design/apps/api/lumen_ingestion/capture/font_instances.py
"""Static instances of a harvested VARIABLE font (Editor Quality Plan 1, item B, 2026-09-04).

A site that ships one variable file (Apollo: ``soehne`` and ``seasonMix``, both with a ``wght``
axis) used to land in the kit as ONE face at weight 400. Neither renderer synthesises bold, so
Bold selected the same face and changed nothing. This module pins the axis at each named
weight with the SAME instancer the Google font library uses (``font_library._instance_bytes``:
OS/2 weight, name table, and RIBBI bits all rewritten to describe the instance), so every
instance is a static face both Skia runtimes match on.

Pure: bytes in, bytes out, no I/O. The evidence builder decides what to do with the plan.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from io import BytesIO

from lumen_api.font_containers import FontContainerError, decode_web_font
from lumen_ingestion.font_library import FontLibraryError, _instance_bytes

#: The named weights a kit face can be asked for by the type roles and the editor's Bold.
INSTANCE_WEIGHTS: tuple[int, ...] = (400, 500, 600, 700)


@dataclass(frozen=True)
class FontInstance:
    weight: int
    italic: bool
    data: bytes
    sha256: str


@dataclass
class FontInstancePlan:
    family: str
    variable: bool
    wght_range: tuple[float, float] | None
    instances: list[FontInstance] = field(default_factory=list)
    skipped_weights: list[int] = field(default_factory=list)
    error: str | None = None


def _sfnt_bytes(data: bytes) -> bytes:
    decoded = decode_web_font(data)
    return decoded.data if decoded is not None else data


def _wght_axis(data: bytes) -> tuple[float, float] | None:
    from fontTools.ttLib import TTFont

    try:
        font = TTFont(BytesIO(data), recalcTimestamp=False, recalcBBoxes=False, lazy=True)
        fvar = font.get("fvar")
    except Exception:  # noqa: BLE001 — not a font we can read: then it is not variable
        return None
    if fvar is None:
        return None
    for axis in fvar.axes:
        if axis.axisTag == "wght":
            return (float(axis.minValue), float(axis.maxValue))
    return None


def plan_font_instances(
    family: str,
    data: bytes,
    *,
    italic: bool = False,
    weights: tuple[int, ...] = INSTANCE_WEIGHTS,
) -> FontInstancePlan:
    """One static instance per weight in ``weights`` that the font's ``wght`` axis covers.

    A static font (no ``fvar``/``wght``) returns ``variable=False`` and no instances. Undecodable
    bytes, or an instancer failure on any weight, return ``error`` and NO instances — the
    caller keeps the original face; a half-instanced family would be worse than none.
    """
    try:
        source = _sfnt_bytes(data)
    except FontContainerError as error:
        return FontInstancePlan(family, False, None, error=str(error))
    axis = _wght_axis(source)
    if axis is None:
        return FontInstancePlan(family, False, None)
    plan = FontInstancePlan(family, True, axis)
    low, high = axis
    for weight in weights:
        if not (low <= weight <= high):
            plan.skipped_weights.append(weight)
            continue
        try:
            instance = _instance_bytes(source, weight, family, italic=italic)
        except (FontLibraryError, Exception) as error:  # noqa: BLE001 — fontTools raises a zoo
            plan.error = f"weight {weight}: {type(error).__name__}: {error}"
            plan.instances.clear()
            return plan
        plan.instances.append(
            FontInstance(weight, italic, instance, hashlib.sha256(instance).hexdigest())
        )
    return plan
```

- [ ] **Step 5: Run the tests**

Run: `... pytest apps/api/tests/test_font_instances.py apps/api/tests/test_font_library.py -q`
Expected: PASS (font_library tests that need the pinned Google clone skip as before).

- [ ] **Step 6: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/capture/font_instances.py subsystems/clue-design/apps/api/tests/variable_font_fixture.py subsystems/clue-design/apps/api/tests/test_font_instances.py
git commit -m "feat(ingestion): instance a variable font into static faces per named weight"
```

---

### Task 4: Wire instancing into the evidence builder; pin italic pass-through

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/evidence_builder.py` (`_AssetJob`, the fonts loop ~185–260, `_call_ingest` ~686)
- Test: `subsystems/clue-design/apps/api/tests/test_evidence_builder_font_instances.py` (new)

**Interfaces:**
- Consumes: `plan_font_instances` (Task 3); `queue(...)` and `_AssetJob` (existing, in `build_evidence`).
- Produces: `FontEvidence.faces` for a variable family = the static instances (weights ascending), each `FontFaceEvidence(weight=<w>, style=<face.style>, asset_id="asset_ing_<sha16>", source_url=<the variable file's url ONLY on the instance at the declared weight, else None>, format="ttf")`. The variable file itself is still rehosted as a captured download (unchanged loop). New `_AssetJob.note: str | None = None`, written into `provenance.notes`.
- Diagnostics on `outcome.diagnostics`: `LUMI0234` (info) `"instanced <family> into static faces <weights> from its variable source (wght <lo>–<hi>)"`; `LUMI0235` (warning) `"could not instance variable font <family>: <error>; the kit keeps its single face"`.

- [ ] **Step 1: Write the failing tests**

```python
# subsystems/clue-design/apps/api/tests/test_evidence_builder_font_instances.py
"""Plan 1 item B: the evidence builder turns a harvested variable font into static kit faces,
ingests each as its own asset, and keeps the variable file rehosted. Also pins that an italic
@font-face declared by the site passes through parse → evidence unchanged (no new harvest code:
the Apollo site simply declares none)."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from fontTools.ttLib import TTFont
from io import BytesIO

from lumen_ingestion.capture.evidence_builder import build_evidence
from lumen_ingestion.capture.snapshot import Download, Stylesheet, load_snapshot
from variable_font_fixture import as_woff2, build_variable_font

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ingestion" / "snapshots"
VF_URL = "https://units.example/fonts/synthetic-vf.woff2"
ITALIC_URL = "https://units.example/fonts/synthetic-italic.woff2"


class _RecordingCore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ingest_asset(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "asset": {"record": {"asset_id": kwargs["asset_id"]}}}


@dataclass
class _Outcome:
    snapshot: object
    tier: str = "static"
    escalated: bool = False
    escalation_reason: str | None = None
    diagnostics: list[dict] = field(default_factory=list)


def _snapshot(css: str, downloads: list[Download]):
    base = load_snapshot(FIXTURES / "insight_static.json")
    return base.model_copy(
        update={
            "stylesheets": [Stylesheet(url="https://units.example/site.css", text=css)],
            "downloads": downloads,
            "computed_samples": None,
        }
    )


def _download(url: str, data: bytes) -> Download:
    return Download(
        url=url, kind="font", content_type="font/woff2",
        bytes_b64=base64.b64encode(data).decode("ascii"),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _weights_ingested(core: _RecordingCore) -> dict[str, int]:
    out = {}
    for call in core.calls:
        if call.get("kind") != "font":
            continue
        data = base64.b64decode(call["bytes_base64"])
        font = TTFont(BytesIO(data))
        if "fvar" in font:
            continue
        out[call["asset_id"]] = font["OS/2"].usWeightClass
    return out


def test_a_variable_face_becomes_four_static_kit_faces(tmp_path: Path) -> None:
    vf = as_woff2(build_variable_font("Synthetic VF"))
    css = f'@font-face{{font-family:"Synthetic VF";src:url({VF_URL}) format("woff2");font-weight:100 900;}}'
    core = _RecordingCore()
    outcome = _Outcome(snapshot=_snapshot(css, [_download(VF_URL, vf)]))
    evidence = build_evidence(outcome, core=core, store_root=str(tmp_path), reporter=lambda s, p: None)

    font = next(f for f in evidence.fonts if f.family == "Synthetic VF")
    assert [face.weight for face in font.faces] == [400, 500, 600, 700]
    assert all(face.asset_id and face.asset_id.startswith("asset_ing_") for face in font.faces)
    assert all(face.format == "ttf" and face.style == "normal" for face in font.faces)
    # The declared (400) instance keeps the variable url so the kit's `source.url` survives.
    assert font.faces[0].source_url == VF_URL
    assert all(face.source_url is None for face in font.faces[1:])
    # Each instance was ingested as sfnt at its own weight, and the variable file still was.
    assert sorted(_weights_ingested(core).values()) == [400, 500, 600, 700]
    assert any(
        base64.b64decode(c["bytes_base64"]) == vf for c in core.calls if c.get("kind") == "font"
    )
    instance_calls = [c for c in core.calls if c["asset_id"] in {f.asset_id for f in font.faces}]
    assert all(c["provenance"]["notes"] and "instance" in c["provenance"]["notes"][0] for c in instance_calls)
    assert all(c["filename"].endswith(".ttf") for c in instance_calls)
    assert [d["code"] for d in outcome.diagnostics if d["code"].startswith("LUMI023")] == ["LUMI0234"]


def test_an_instancing_failure_keeps_the_single_face_and_says_so(tmp_path: Path, monkeypatch) -> None:
    import lumen_ingestion.capture.evidence_builder as eb
    from lumen_ingestion.capture.font_instances import FontInstancePlan

    monkeypatch.setattr(
        eb, "plan_font_instances",
        lambda family, data, **kw: FontInstancePlan(family, True, (300.0, 900.0), error="boom"),
    )
    vf = as_woff2(build_variable_font("Synthetic VF"))
    css = f'@font-face{{font-family:"Synthetic VF";src:url({VF_URL}) format("woff2");}}'
    core = _RecordingCore()
    outcome = _Outcome(snapshot=_snapshot(css, [_download(VF_URL, vf)]))
    evidence = build_evidence(outcome, core=core, store_root=str(tmp_path), reporter=lambda s, p: None)
    font = next(f for f in evidence.fonts if f.family == "Synthetic VF")
    assert [face.weight for face in font.faces] == [400]
    assert font.faces[0].asset_id and font.faces[0].source_url == VF_URL
    assert [d["code"] for d in outcome.diagnostics if d["code"].startswith("LUMI023")] == ["LUMI0235"]


def test_a_declared_italic_face_passes_through_to_evidence(tmp_path: Path) -> None:
    upright = as_woff2(build_variable_font("Synthetic VF"))
    italic = as_woff2(build_variable_font("Synthetic VF", wght=(400, 700)))
    css = (
        f'@font-face{{font-family:"Synthetic VF";src:url({VF_URL});font-style:normal;}}'
        f'@font-face{{font-family:"Synthetic VF";src:url({ITALIC_URL});font-style:italic;}}'
    )
    core = _RecordingCore()
    outcome = _Outcome(snapshot=_snapshot(css, [_download(VF_URL, upright), _download(ITALIC_URL, italic)]))
    evidence = build_evidence(outcome, core=core, store_root=str(tmp_path), reporter=lambda s, p: None)
    font = next(f for f in evidence.fonts if f.family == "Synthetic VF")
    italics = [face for face in font.faces if face.style == "italic"]
    uprights = [face for face in font.faces if face.style == "normal"]
    assert [f.weight for f in uprights] == [400, 500, 600, 700]
    assert [f.weight for f in italics] == [400, 500, 600, 700]
    italic_ids = {f.asset_id for f in italics}
    italic_calls = [c for c in core.calls if c["asset_id"] in italic_ids]
    assert all(TTFont(BytesIO(base64.b64decode(c["bytes_base64"])))["OS/2"].fsSelection & 1 for c in italic_calls)
```

If `build_evidence` needs more on `outcome` than the dataclass above provides (it reads `outcome.snapshot`, `outcome.diagnostics`, and — check — `outcome.snapshots` / `outcome.tier`), add those attributes; do not stub `build_evidence` itself.

- [ ] **Step 2: Run to verify they fail**

Run: `... pytest apps/api/tests/test_evidence_builder_font_instances.py -q`
Expected: FAIL — one face at 400 (first test), `plan_font_instances` not an attribute of `evidence_builder` (second test).

- [ ] **Step 3: Extend `_AssetJob` and `_call_ingest`**

```python
@dataclass
class _AssetJob:
    url: str | None
    sha256: str
    body: bytes
    kind: str  # "font" | "image" (ingest kind hint; images/logos left to sniff)
    filename: str
    content_type: str | None
    #: A provenance note for a DERIVED asset (a static instance of a variable font); None for a
    #: plain rehost.
    note: str | None = None
```

In `_call_ingest`, replace `"notes": []` with `"notes": [job.note] if job.note else []`.

- [ ] **Step 4: Instance inside the fonts loop**

Add the import at the top of `evidence_builder.py`: `from lumen_ingestion.capture.font_instances import plan_font_instances`.

In the `for face in font.faces:` loop, immediately after the `if face.source_url and asset_id is None:` block and BEFORE `faces.append(FontFaceEvidence(...))`, insert:

```python
            # Plan 1 item B (2026-09-04): a variable source becomes one static face per named
            # weight. The variable file itself stays rehosted (the downloads loop below queues
            # every captured byte), but it is NOT a kit face — a kit face is something both
            # renderers can match by weight, and a variable file is matched at its default only.
            if face_sha and asset_id is not None and face.style in ("normal", "italic"):
                plan = plan_font_instances(
                    font.family, sha_bytes[face_sha], italic=(face.style == "italic")
                )
                if plan.variable and plan.instances:
                    declared_weight = face.weight or 400
                    for instance in plan.instances:
                        if instance.sha256 not in jobs:
                            sha_bytes[instance.sha256] = instance.data
                            sha_ct[instance.sha256] = "font/ttf"
                            suffix = "-italic" if instance.italic else ""
                            jobs[instance.sha256] = _AssetJob(
                                url=face.source_url,
                                sha256=instance.sha256,
                                body=instance.data,
                                kind="font",
                                filename=(
                                    f"instance-{instance.sha256[:_SLURP_SHA_CHARS]}-"
                                    f"{font.family.replace(' ', '')}-{instance.weight}{suffix}.ttf"
                                ),
                                content_type="font/ttf",
                                note=(
                                    f"static instance wght={instance.weight}"
                                    f"{' italic' if instance.italic else ''} of variable font "
                                    f"{short_url(face.source_url)} (sha256 {face_sha[:12]})"
                                ),
                            )
                        faces.append(
                            FontFaceEvidence(
                                weight=instance.weight,
                                style=face.style,
                                asset_id=f"asset_ing_{instance.sha256[:16]}",
                                source_url=face.source_url if instance.weight == declared_weight else None,
                                format="ttf",
                            )
                        )
                    lo, hi = plan.wght_range or (0.0, 0.0)
                    instance_diagnostics.append(
                        {
                            "code": "LUMI0234",
                            "severity": "info",
                            "message": (
                                f"instanced {font.family} into static faces "
                                f"{[i.weight for i in plan.instances]} from its variable source "
                                f"(wght {lo:g}–{hi:g})"
                            ),
                            "family": font.family,
                        }
                    )
                    continue
                if plan.variable and plan.error:
                    instance_diagnostics.append(
                        {
                            "code": "LUMI0235",
                            "severity": "warning",
                            "message": (
                                f"could not instance variable font {font.family}: {plan.error}; "
                                f"the kit keeps its single face"
                            ),
                            "family": font.family,
                        }
                    )
```

Declare `instance_diagnostics: list[dict] = []` next to `face_failures` above the loop. If no instance carries the declared weight (e.g. the axis starts at 500 and the face declared 400), put `source_url` on the FIRST instance instead — add that fallback after the loop: `if not any(f.source_url for f in faces if f.format == "ttf") and faces: faces[0] = faces[0].model_copy(update={"source_url": face.source_url})` — only inside the `plan.variable and plan.instances` branch.

Where `geometry.diagnostics` are extended onto `outcome_diagnostics` (~line 330), add the same for `instance_diagnostics`:

```python
    if instance_diagnostics and isinstance(outcome_diagnostics, list):
        outcome_diagnostics.extend(instance_diagnostics)
```

(`short_url` and `_SLURP_SHA_CHARS` already exist in the module.)

- [ ] **Step 5: Run the new tests, then the neighbours**

Run: `... pytest apps/api/tests/test_evidence_builder_font_instances.py apps/api/tests/test_ingestion_capture.py apps/api/tests/test_ingestion_asset_slurp.py apps/api/tests/test_ingestion_normalizer.py -q`
Expected: all PASS. (`test_ingestion_normalizer` golden fixtures use static faces / no bytes, so they must not move.)

- [ ] **Step 6 (DB, throwaway DSN only): the existing end-to-end font test still passes**

Run with `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55040/clue_plan1_test`: `... pytest apps/api/tests/test_ingestion_font_decode.py -q`
Expected: PASS (it feeds a static Inter WOFF2 through the pipeline; unaffected).

- [ ] **Step 7: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/capture/evidence_builder.py subsystems/clue-design/apps/api/tests/test_evidence_builder_font_instances.py
git commit -m "feat(ingestion): emit static instances of a variable font as kit faces (LUMI0234/0235)"
```

---

### Task 5: Backfill script — re-derive stored kits' type units, publish next version, repin documents

**Files:**
- Create: `subsystems/clue-design/scripts/rederive_kit_type_units.py`
- Test: `subsystems/clue-design/apps/api/tests/test_rederive_kit_type_units.py`

**Interfaces:**
- Consumes: `design_ingestion_job.evidence_json` (the job's `BrandEvidence` dump), `design_brand_kit` rows (`brand_kit_json`, `brand_summary_json`, `diagnostics_json`, `source`), `HybridRepository(workspace_id=...).publish_next_brand_kit_version(brand_kit, brand_summary, diagnostics, source, *, expected_base_version) -> JsonObject`, `resolve_anchors`, `build_type_styles`, `custodied_weights`, `LINE_HEIGHT_RATIO_RANGE` (Task 2).
- Produces: `rederive_kit_type_units(conn, *, workspace_id: str | None, brand_kit_id: str | None, apply: bool, repin_documents: bool) -> Summary` with `Summary(examined: int, changed: int, published: int, repinned_documents: int, skipped_no_evidence: int, failed: int)`. CLI: `--apply`, `--workspace`, `--kit`, `--repin-documents`; dry run by default; reads `CLUE_DATABASE_URL`.
- Kit JSON path written: `brand_kit["tokens"]["typography"]["type.<role>"]["value"]["default"]["line_height" | "letter_spacing"]` — ONLY those two keys, only for roles whose recomputed value differs.

- [ ] **Step 1: Write the failing test** (pattern: `tests/test_decode_stored_web_fonts.py` — `load_script()` via importlib with `sys.modules[spec.name] = module` before `exec_module`, the `conn` psycopg fixture, `make_client`)

```python
# subsystems/clue-design/apps/api/tests/test_rederive_kit_type_units.py
"""Plan 1 item A backfill: a stored kit whose evidence carried px/16 type units is re-derived
from that evidence (corrected in memory), published as a NEW immutable version, and the
documents pinned to the old version follow it when asked. Throwaway DSN only."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from conftest import make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "rederive_kit_type_units.py"
EVIDENCE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ingestion" / "evidence_website_insight.json"


def load_script():
    spec = importlib.util.spec_from_file_location("rederive_kit_type_units", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    return make_client(app)


@pytest.fixture()
def conn():
    dsn = (
        os.environ["CLUE_DATABASE_URL"]
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
    )
    with psycopg.connect(dsn) as connection:
        yield connection


def _evidence_with_px16_headline() -> dict:
    evidence = json.loads(EVIDENCE_FIXTURE.read_text())
    evidence["type_samples"] = [
        {
            "label": "h1", "family": "Aeonik", "weight": 600, "size_px": 72.0,
            "line_height": 4.5, "letter_spacing": -0.045,
            "pointer": {"source": "website", "locator": "rendered :: h1"},
        },
        {
            "label": "body", "family": "Aeonik", "weight": 400, "size_px": 18.0,
            "line_height": 1.6875, "letter_spacing": 0.0105,
            "pointer": {"source": "website", "locator": "rendered :: body"},
        },
    ]
    return evidence


def _publish_kit_from_evidence(client: TestClient, evidence: dict) -> tuple[str, int]:
    """Drive the real website pipeline in-process (fake capture + fake evidence), exactly as
    tests/test_ingestion_font_decode.py does, so the kit row, its job row, and the job's
    evidence_json are all real. Returns (brand_kit_id, version)."""
    ...  # copy the fake_capture / fake_build_evidence / execute_ingestion_job block from
         # test_ingestion_font_decode.py::test_website_ingestion_persists_a_harvested_woff2_face_as_ttf,
         # returning `BrandEvidence.model_validate(evidence)` from fake_build_evidence and
         # reading (brand_kit_id, brand_kit_version) off the finished job row.


def _pin_document(conn, workspace_id: str, document_id: str, kit_id: str, version: int) -> None:
    conn.execute(
        "UPDATE design_document SET effective_brand_kit_id=%s, effective_brand_kit_version=%s,"
        " effective_brand_kit_source='workspace' WHERE id=%s AND workspace_id=%s",
        (kit_id, version, document_id, workspace_id),
    )
    conn.commit()


def test_dry_run_reports_and_writes_nothing(client: TestClient, conn) -> None:
    kit_id, version = _publish_kit_from_evidence(client, _evidence_with_px16_headline())
    script = load_script()
    summary = script.rederive_kit_type_units(conn, workspace_id=HybridRepository().workspace_id, brand_kit_id=kit_id, apply=False, repin_documents=False)
    assert summary.examined == 1 and summary.changed == 1 and summary.published == 0
    latest = HybridRepository().require_brand_kit(kit_id)
    assert latest["version"] == version


def test_apply_publishes_the_next_version_with_corrected_units_and_repins(client: TestClient, conn) -> None:
    workspace_id = HybridRepository().workspace_id
    kit_id, version = _publish_kit_from_evidence(client, _evidence_with_px16_headline())
    before = HybridRepository().require_brand_kit(kit_id)["brand_kit"]
    # Task 2's guard already kept 4.5 out of the kit; the derived default (1.1) is what v1 holds.
    assert before["tokens"]["typography"]["type.headline"]["value"]["default"]["line_height"] == 1.1

    doc = client.post("/documents", json={"title": "pinned", "doc_kind": "ad"}).json()  # adjust to the real create route/body
    _pin_document(conn, workspace_id, doc["id"], kit_id, version)

    script = load_script()
    summary = script.rederive_kit_type_units(conn, workspace_id=workspace_id, brand_kit_id=kit_id, apply=True, repin_documents=True)
    assert summary.published == 1 and summary.repinned_documents == 1

    after = HybridRepository().require_brand_kit(kit_id)
    assert after["version"] == version + 1
    headline = after["brand_kit"]["tokens"]["typography"]["type.headline"]["value"]["default"]
    assert headline["line_height"] == 1.0  # 4.5 × 16 = 72px over 72px
    assert headline["letter_spacing"] == -0.01  # -0.045 × 16 = -0.72px over 72px
    body = after["brand_kit"]["tokens"]["typography"]["type.body"]["value"]["default"]
    assert body["line_height"] == 1.6875  # a rendered sample within range is recomputed to itself? NO —
    # rendered samples are ALWAYS px-derived, so body becomes 1.6875 × 16 / 18 = 1.5. Assert that:
    assert body["line_height"] == 1.5
    assert any(d["code"] == "LUMI0233" for d in after["diagnostics"])
    # Everything else in the kit is byte-identical.
    for path, style in after["brand_kit"]["tokens"]["typography"].items():
        for key, value in style["value"]["default"].items():
            if key not in ("line_height", "letter_spacing"):
                assert before["tokens"]["typography"][path]["value"]["default"][key] == value

    row = conn.execute(
        "SELECT effective_brand_kit_version FROM design_document WHERE id=%s", (doc["id"],)
    ).fetchone()
    assert row[0] == version + 1


def test_a_kit_with_no_stored_evidence_is_skipped_loudly(client: TestClient, conn, capsys) -> None:
    kit_id, _ = _publish_kit_from_evidence(client, _evidence_with_px16_headline())
    conn.execute("UPDATE design_ingestion_job SET evidence_json=NULL WHERE brand_kit_id=%s", (kit_id,))
    conn.commit()
    summary = load_script().rederive_kit_type_units(conn, workspace_id=HybridRepository().workspace_id, brand_kit_id=kit_id, apply=True, repin_documents=False)
    assert summary.skipped_no_evidence == 1 and summary.published == 0
    assert "no stored evidence" in capsys.readouterr().out
```

Resolve the two `adjust` notes by reading the real routes (`grep -n '@app.post("/documents' apps/api/lumen_api/main.py`) and the pipeline test; if `design_ingestion_job.evidence_json` cannot be nulled by an UPDATE (a guard trigger), delete the job row for that kit instead. Report which.

- [ ] **Step 2: Run to verify it fails**

Run (throwaway DSN): `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55040/clue_plan1_test ... pytest apps/api/tests/test_rederive_kit_type_units.py -q`
Expected: FAIL — script file not found.

- [ ] **Step 3: Write the script**

```python
#!/usr/bin/env python
"""Re-derive stored brand kits' type units after the px/16 fix (Editor Quality Plan 1, item A).

Before 2026-09-04 the harvester stored every px line-height and letter-spacing divided by the
ROOT size (16) instead of the element's. The kit's `type.*` roles inherited that: Apollo's
headline carried line_height 4.5. This script recomputes ONLY `line_height` and
`letter_spacing` of `tokens.typography.type.*` from the kit's stored ingestion evidence
(corrected in memory the same way the fixed parser would have produced it), publishes the
result as the kit's NEXT version (kit versions are immutable), and — with --repin-documents —
moves the documents pinned to the old version onto the new one.

Dry run by default: prints what would change and writes nothing.

    CLUE_DATABASE_URL=... python scripts/rederive_kit_type_units.py [--workspace WS] [--kit KIT]
    CLUE_DATABASE_URL=... python scripts/rederive_kit_type_units.py --apply --repin-documents
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Optional

import psycopg

from lumen_api.design_store import HybridRepository
from lumen_ingestion.evidence import BrandEvidence
from lumen_ingestion.normalizer.typography import (
    LINE_HEIGHT_RATIO_RANGE,
    build_type_styles,
    custodied_weights,
    resolve_anchors,
)

ROOT_PX = 16.0


@dataclass
class Summary:
    examined: int = 0
    changed: int = 0
    published: int = 0
    repinned_documents: int = 0
    skipped_no_evidence: int = 0
    failed: int = 0


def correct_type_units(evidence: BrandEvidence) -> BrandEvidence:
    """Undo px/16 on the samples that were px-derived.

    Rendered samples (`locator` starts with "rendered ::") are ALWAYS computed px values, so both
    fields are re-based on the sample's own size. Declared-CSS samples are ambiguous (an `em`
    value was stored correctly), so only a line-height outside the sane band — which can only
    have been px — is re-based; their letter-spacing is left alone.
    """
    low, high = LINE_HEIGHT_RATIO_RANGE
    samples = []
    for sample in evidence.type_samples:
        update: dict = {}
        size = sample.size_px
        rendered = sample.pointer.locator.startswith("rendered ::")
        if size:
            if sample.line_height and (rendered or not (low <= sample.line_height <= high)):
                update["line_height"] = round(sample.line_height * ROOT_PX / size, 4)
            if rendered and sample.letter_spacing is not None:
                update["letter_spacing"] = round(sample.letter_spacing * ROOT_PX / size, 4)
        samples.append(sample.model_copy(update=update) if update else sample)
    return evidence.model_copy(update={"type_samples": samples})


def recomputed_units(kit: dict, evidence: BrandEvidence) -> dict[str, dict[str, float]]:
    """{ "type.<role>": {"line_height": x, "letter_spacing": y} } for roles whose values move."""
    typography = kit.get("tokens", {}).get("typography", {})
    cta = typography.get("type.cta", {}).get("value", {}).get("default", {}).get("color", "text.inverse")
    styles, _ = build_type_styles(resolve_anchors(evidence), cta_color=cta, custodied=custodied_weights(evidence))
    changes: dict[str, dict[str, float]] = {}
    for path, style in styles.items():
        current = typography.get(path, {}).get("value", {}).get("default")
        if not current:
            continue
        delta = {
            key: style[key]
            for key in ("line_height", "letter_spacing")
            if current.get(key) != style[key]
        }
        if delta:
            changes[path] = delta
    return changes


def _latest_kits(conn, workspace_id: Optional[str], brand_kit_id: Optional[str]):
    sql = (
        "SELECT DISTINCT ON (workspace_id, brand_kit_id) workspace_id, brand_kit_id, version"
        " FROM design_brand_kit WHERE brand_kit_id LIKE 'brand_kit_ing_%%'"
    )
    params: dict = {}
    if workspace_id:
        sql += " AND workspace_id = %(ws)s"
        params["ws"] = workspace_id
    if brand_kit_id:
        sql += " AND brand_kit_id = %(kit)s"
        params["kit"] = brand_kit_id
    sql += " ORDER BY workspace_id, brand_kit_id, version DESC"
    return conn.execute(sql, params).fetchall()


def _latest_evidence(conn, workspace_id: str, brand_kit_id: str) -> Optional[BrandEvidence]:
    row = conn.execute(
        "SELECT evidence_json FROM design_ingestion_job"
        " WHERE workspace_id = %s AND brand_kit_id = %s AND evidence_json IS NOT NULL"
        " ORDER BY created_at DESC LIMIT 1",
        (workspace_id, brand_kit_id),
    ).fetchone()
    if row is None:
        return None
    raw = row[0]
    return BrandEvidence.model_validate(json.loads(raw) if isinstance(raw, str) else raw)


def _repin(conn, workspace_id: str, brand_kit_id: str, old: int, new: int) -> int:
    cursor = conn.execute(
        "UPDATE design_document SET effective_brand_kit_version = %s, updated_at = now()"
        " WHERE workspace_id = %s AND effective_brand_kit_id = %s AND effective_brand_kit_version = %s",
        (new, workspace_id, brand_kit_id, old),
    )
    conn.commit()
    return cursor.rowcount


def rederive_kit_type_units(
    conn, *, workspace_id: Optional[str], brand_kit_id: Optional[str], apply: bool, repin_documents: bool
) -> Summary:
    summary = Summary()
    for ws, kit_id, version in _latest_kits(conn, workspace_id, brand_kit_id):
        summary.examined += 1
        evidence = _latest_evidence(conn, ws, kit_id)
        if evidence is None:
            print(f"SKIP {ws}/{kit_id} v{version}: no stored evidence to re-derive from")
            summary.skipped_no_evidence += 1
            continue
        repo = HybridRepository(workspace_id=ws)
        row = repo.require_brand_kit(kit_id, version)
        kit = row["brand_kit"]
        changes = recomputed_units(kit, correct_type_units(evidence))
        if not changes:
            print(f"OK   {ws}/{kit_id} v{version}: type units already element-relative")
            continue
        summary.changed += 1
        for path, delta in changes.items():
            print(f"     {ws}/{kit_id} v{version} {path}: {delta}")
        if not apply:
            continue
        try:
            for path, delta in changes.items():
                kit["tokens"]["typography"][path]["value"]["default"].update(delta)
            diagnostics = list(row["diagnostics"] or []) + [
                {
                    "code": "LUMI0233",
                    "severity": "info",
                    "message": (
                        f"type units re-derived from stored evidence on 2026-09-04 (px/16 fix): "
                        f"{', '.join(changes)}"
                    ),
                }
            ]
            published = repo.publish_next_brand_kit_version(
                kit, row["brand_summary"], diagnostics, row["source"], expected_base_version=version
            )
            new_version = int(published["version"])
            summary.published += 1
            print(f"PUB  {ws}/{kit_id} v{version} -> v{new_version}")
            if repin_documents:
                count = _repin(conn, ws, kit_id, version, new_version)
                summary.repinned_documents += count
                print(f"PIN  {ws}/{kit_id}: {count} document(s) v{version} -> v{new_version}")
        except Exception as error:  # noqa: BLE001 — one kit must not stop the sweep
            summary.failed += 1
            print(f"FAIL {ws}/{kit_id} v{version}: {type(error).__name__}: {error}", file=sys.stderr)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="publish new kit versions")
    parser.add_argument("--workspace", default=None, help="limit to one workspace id")
    parser.add_argument("--kit", default=None, help="limit to one brand_kit_id")
    parser.add_argument("--repin-documents", action="store_true", help="move documents pinned to the old version onto the new one")
    args = parser.parse_args()
    database_url = os.environ.get("CLUE_DATABASE_URL", "")
    if not database_url:
        print("CLUE_DATABASE_URL is required", file=sys.stderr)
        return 2
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn:
        summary = rederive_kit_type_units(
            conn, workspace_id=args.workspace, brand_kit_id=args.kit, apply=args.apply, repin_documents=args.repin_documents
        )
    mode = "applied" if args.apply else "dry run — nothing written"
    print(
        f"{mode}: {summary.examined} examined, {summary.changed} needing change, {summary.published} published,"
        f" {summary.repinned_documents} documents repinned, {summary.skipped_no_evidence} without evidence,"
        f" {summary.failed} failed"
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`HybridRepository(workspace_id=...)` requires the workspace to be explicit — check its constructor signature; if it takes the workspace from env only, use the `_bridge._run(lambda conn: design_brand.publish_next_brand_kit_version(...))` shape shown in `design_store.py:835` with `workspace_id=ws`. Confirm `row["source"]` is the string column (`_brand_kit_from_row` in `subsystems/design/clue_design/brand.py:42`).

- [ ] **Step 4: Run the tests (throwaway DSN)**

Run: `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55040/clue_plan1_test ... pytest apps/api/tests/test_rederive_kit_type_units.py apps/api/tests/test_decode_stored_web_fonts.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/scripts/rederive_kit_type_units.py subsystems/clue-design/apps/api/tests/test_rederive_kit_type_units.py
git commit -m "feat(design): backfill script re-derives stored kits' type units and repins documents"
```

---

### Task 6: Editor — Bold/Italic disabled with a reason when the kit has no face

**Files:**
- Modify: `apps/frontend/src/features/design-editor/engine/scene/canvaskit/loadCanvasKit.ts` (new export next to `hasItalicFace`)
- Modify: `apps/frontend/src/features/design-editor/components/scene-text-toolbar.logic.ts` (`sceneTextMarkState`, new `sceneTextMarkUnavailableReason`, `SceneTextFaceAvailability`)
- Modify: `apps/frontend/src/features/design-editor/components/scene-text-toolbar.tsx` (props `family`, `faces`; `title`)
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-text-edit.ts` (`SceneTextEditModel.family`)
- Modify: `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx` (~2427 `applyMark`, ~2551 toolbar props)
- Test: `apps/frontend/src/features/design-editor/components/scene-text-toolbar.logic.test.ts` (extend), `apps/frontend/src/features/design-editor/engine/scene/__tests__/loadCanvasKit.test.ts` (new non-wasm describe block)

**Interfaces:**
- Produces: `boldChangesFace(family: string): boolean` (loadCanvasKit.ts) — true when the registered face CSS3-selected for weight 700 differs from the one selected for 400 (same Inter fallback rule as `hasItalicFace`).
- `export interface SceneTextFaceAvailability { bold: boolean; italic: boolean }`
- `sceneTextMarkUnavailableReason(channel: SceneTextMarkChannel, family: string, faces: SceneTextFaceAvailability): string | null`
- `sceneTextMarkState(channel, format, { collapsed, inert, family, faces }): { pressed: TriState; disabled: boolean; reason: string | null }`
- `SceneTextEditModel.family: string` (the node's declared family, un-quoted; `model.style.fontFamily` stays the DOM stack).

- [ ] **Step 1: Write the failing logic tests** (append to `scene-text-toolbar.logic.test.ts`; it uses `node:test` + `node:assert/strict`)

```ts
test("a mark whose face the kit lacks is disabled and says why", () => {
  const state: RangeFormatState = {
    bold: "off", italic: "off", underline: "off", strikethrough: "off",
    fill: { kind: "uniform", paint: null },
  };
  const faces = { bold: false, italic: false };
  assert.deepEqual(
    sceneTextMarkState("bold", state, { collapsed: false, inert: false, family: "seasonMix", faces }),
    { pressed: "off", disabled: true, reason: "No bold face for “seasonMix” in the brand kit" },
  );
  assert.deepEqual(
    sceneTextMarkState("italic", state, { collapsed: false, inert: false, family: "seasonMix", faces }),
    { pressed: "off", disabled: true, reason: "No italic face for “seasonMix” in the brand kit" },
  );
  // Underline/strikethrough never depend on a face.
  assert.equal(
    sceneTextMarkState("underline", state, { collapsed: false, inert: false, family: "seasonMix", faces }).disabled,
    false,
  );
  // With the faces present, nothing changes from before.
  const ok = { bold: true, italic: true };
  assert.deepEqual(
    sceneTextMarkState("bold", state, { collapsed: false, inert: false, family: "seasonMix", faces: ok }),
    { pressed: "off", disabled: false, reason: null },
  );
});

test("the face reason is exact copy, per channel and family", () => {
  assert.equal(sceneTextMarkUnavailableReason("bold", "Söhne", { bold: false, italic: true }), "No bold face for “Söhne” in the brand kit");
  assert.equal(sceneTextMarkUnavailableReason("italic", "Söhne", { bold: true, italic: false }), "No italic face for “Söhne” in the brand kit");
  assert.equal(sceneTextMarkUnavailableReason("bold", "Söhne", { bold: true, italic: false }), null);
  assert.equal(sceneTextMarkUnavailableReason("strikethrough", "Söhne", { bold: false, italic: false }), null);
});
```

Update the four existing `sceneTextMarkState(...)` calls in that file to pass `family: "Inter", faces: { bold: true, italic: true }` and expect `reason: null` in their `deepEqual`s.

- [ ] **Step 2: Write the failing registry test** (in `__tests__/loadCanvasKit.test.ts`, a NEW top-level `describe` that is NOT wrapped in `describe.skipIf(!present)` — `registerKitFontFaces` records faces synchronously before any wasm exists, so this needs no CanvasKit)

```ts
describe("boldChangesFace (Plan 1 item B)", () => {
  beforeEach(() => {
    resetCanvasKitForTests();
  });

  it("is false for a single-face family and true once a heavier face registers", () => {
    const regular = fontArrayBuffer("Inter-Regular.ttf");
    const bold = fontArrayBuffer("Inter-Bold.ttf");
    registerKitFontFaces([{ key: "seasonMix@a", family: "seasonMix", bytes: regular }]);
    expect(boldChangesFace("seasonMix")).toBe(false);
    registerKitFontFaces([{ key: "seasonMix@b", family: "seasonMix", bytes: bold }]);
    expect(boldChangesFace("seasonMix")).toBe(true);
  });

  it("an unregistered family answers for Inter, like hasItalicFace", () => {
    expect(boldChangesFace("Nope")).toBe(false); // nothing registered at all
    registerKitFontFaces([
      { key: "Inter@r", family: "Inter", bytes: fontArrayBuffer("Inter-Regular.ttf") },
      { key: "Inter@b", family: "Inter", bytes: fontArrayBuffer("Inter-Bold.ttf") },
    ]);
    expect(boldChangesFace("Nope")).toBe(true);
  });
});
```

(`fontArrayBuffer` and `resetCanvasKitForTests` already exist in that file; add `boldChangesFace` to its import.)

- [ ] **Step 3: Run both to verify they fail**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/components/scene-text-toolbar.logic.test.ts; npx vitest run src/features/design-editor/engine/scene/__tests__/loadCanvasKit.test.ts`
Expected: FAIL — `sceneTextMarkUnavailableReason` not exported; `boldChangesFace` not exported.

- [ ] **Step 4: Add `boldChangesFace`** (loadCanvasKit.ts, directly after `hasItalicFace`)

```ts
const REGULAR_REQUEST = 400;
const BOLD_REQUEST = 700;

/**
 * Plan 1 item B (2026-09-04): whether asking this family for Bold (700) selects a
 * DIFFERENT registered face than Regular (400) does. Neither renderer synthesises
 * bold, so when the answer is no, the Bold toggle would write a weight nobody can
 * paint — the toolbar disables it and says why. Same Inter fallback as
 * `hasItalicFace`: an unregistered family renders in Inter, so Inter's faces answer.
 */
export function boldChangesFace(family: string): boolean {
  const resolved = familyFaces.has(family) ? family : INTER_FAMILY;
  const faces = familyFaces.get(resolved) ?? [];
  if (faces.length === 0) {
    return false;
  }
  const regular = selectFace(faces, REGULAR_REQUEST, false);
  const bold = selectFace(faces, BOLD_REQUEST, false);
  return regular !== null && bold !== null && regular.alias !== bold.alias;
}
```

- [ ] **Step 5: Extend the toolbar logic**

In `scene-text-toolbar.logic.ts`:

```ts
/** Which face-dependent marks the selected node's family can actually paint. */
export interface SceneTextFaceAvailability {
  bold: boolean;
  italic: boolean;
}

/**
 * Why a mark cannot be applied, or null. Only bold and italic need a face; the
 * copy is the founder-ratified sentence (Plan 1, 2026-09-04) and names the family
 * so the user knows which font to add to the kit.
 */
export function sceneTextMarkUnavailableReason(
  channel: SceneTextMarkChannel,
  family: string,
  faces: SceneTextFaceAvailability,
): string | null {
  if (channel === "bold" && !faces.bold) {
    return `No bold face for “${family}” in the brand kit`;
  }
  if (channel === "italic" && !faces.italic) {
    return `No italic face for “${family}” in the brand kit`;
  }
  return null;
}

export function sceneTextMarkState(
  channel: SceneTextMarkChannel,
  format: RangeFormatState,
  {
    collapsed,
    inert,
    family,
    faces,
  }: { collapsed: boolean; inert: boolean; family: string; faces: SceneTextFaceAvailability },
): { pressed: TriState; disabled: boolean; reason: string | null } {
  const reason = sceneTextMarkUnavailableReason(channel, family, faces);
  return { pressed: format[channel], disabled: collapsed || inert || reason !== null, reason };
}
```

Update the docblock above `sceneTextMarkState` to add the third gate ("`faces` — the kit has no face for this mark; the button carries the reason as its title").

- [ ] **Step 6: Thread family and faces through the toolbar and the canvas**

`scene-text-toolbar.tsx`: add to `SceneTextToolbarProps`:

```ts
  /** The node's declared family, for the disabled-mark reason. */
  family: string;
  /** Which face-dependent marks that family can paint (Plan 1 item B). */
  faces: SceneTextFaceAvailability;
```

destructure both; in the mark row pass `{ collapsed, inert, family, faces }` to `sceneTextMarkState` and render:

```tsx
              title={
                state.reason ??
                (control.shortcut ? `${control.label} (${control.shortcut})` : control.label)
              }
```

`scene-text-edit.ts`: add `family: string;` to `SceneTextEditModel` (next to `nodeId`) and set `family: text.fontFamily` where the model is built (~line 434, beside `style: { fontFamily: domFontFamilyStack(text.fontFamily), ... }`).

`scene-artifact-canvas.tsx` (the caret session component that renders `<SceneTextToolbar>`):

```ts
  const faces: SceneTextFaceAvailability = {
    bold: boldChangesFace(model.family),
    italic: hasItalicFace(model.family),
  };
```

(import `boldChangesFace`, `hasItalicFace` from `../engine/scene/canvaskit/loadCanvasKit` — check the existing import path style in that file — and `SceneTextFaceAvailability`, `sceneTextMarkUnavailableReason` from `./scene-text-toolbar.logic`). Pass `family={model.family}` and `faces={faces}` to `<SceneTextToolbar>`. In `applyMark`, refuse the chord path the same way the button does:

```ts
  const applyMark = (channel: SceneTextMarkChannel) => {
    if (sceneTextMarkUnavailableReason(channel, model.family, faces) !== null) {
      return; // ⌘B/⌘I on a family with no such face: the button is disabled and says why
    }
    ...
```

Search the repo for other `sceneTextMarkState(` / `<SceneTextToolbar` callers (`grep -rn "sceneTextMarkState(\|<SceneTextToolbar" apps/frontend/src`) and update every one.

- [ ] **Step 7: Run the focused tests, then the gate**

Run: `npx tsx --test src/features/design-editor/components/scene-text-toolbar.logic.test.ts && npx vitest run src/features/design-editor/engine/scene/__tests__/loadCanvasKit.test.ts && npm run design-system:build && npm run lint && npm run build`
Expected: all PASS, gate green (2 pre-existing lint warnings are known).

- [ ] **Step 8: Commit**

```bash
git add apps/frontend/src/features/design-editor/engine/scene/canvaskit/loadCanvasKit.ts apps/frontend/src/features/design-editor/components/scene-text-toolbar.logic.ts apps/frontend/src/features/design-editor/components/scene-text-toolbar.tsx apps/frontend/src/features/design-editor/adapter/scene-text-edit.ts apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx apps/frontend/src/features/design-editor/components/scene-text-toolbar.logic.test.ts apps/frontend/src/features/design-editor/engine/scene/__tests__/loadCanvasKit.test.ts
git commit -m "feat(design-editor): Bold/Italic disable with a reason when the kit has no such face"
```

---

### Task 7 (controller, not delegated): live proof on the Apollo kit, records

- [ ] Re-ingest `https://www.apollo.io` into `brand_kit_ing_10c2b0ea17054c668384ae5e91abfebb` (the same `POST /brand-kits/ingest/website` body that produced v2: `{"url": "https://www.apollo.io", "name": "Apollo", "brand_kit_id": "...", "force_render": true}`) on the colombo stack; wait for the job; confirm v3: `type.headline.line_height` ≈ 1.0, `letter_spacing` ≈ -0.01, `font_weight` 600 (550 snapped to the nearest custodied, heavier on tie), `assets.fonts.brand.faces` = 400/500/600/700 with distinct asset ids, LUMI0234 ×2 in the job diagnostics, no LUMI0232 for headline.
- [ ] Run `scripts/rederive_kit_type_units.py` dry-run against colombo (expect the remaining `brand_kit_ing_*` kits listed), then `--apply --repin-documents --workspace ws_8163898e0d0e4420b578bdbc57d7f3e4 --kit brand_kit_ing_10c2b0ea…` ONLY if the re-ingest did not already move the Apollo documents (it does not repin; the script does). Record before/after pins for `doc_cf05190c…`.
- [ ] Browser (gstack `/browse`): open the Apollo artifact, enter the headline, select a range: Bold visibly thickens on canvas; export SVG embeds a 600/700 seasonMix instance; Italic is disabled with title `No italic face for “seasonMix” in the brand kit`. Screenshot paths recorded.
- [ ] Write `_memory/2026-09-04-plan1-type-units-and-faces.md` (+ README index line); add a CLAUDE.md backlog bullet `[design×ingestion] type units + instanced faces` with the backfill owner action per environment; tick Plan 1 in the roadmap's status header. Commit.

---

## Self-review

- **Spec coverage.** Item A: parser (T1), guard (T2), backfill + repin (T5), live proof (T7). Item B: instancing (T3, T4), italic harvest pinned (T4 test 3), toolbar disabled-with-reason (T6), live proof (T7). Letter-spacing added to A on evidence (same root cause, same fix).
- **Placeholders.** The two `adjust` notes in T5 and the `...` body of `_publish_kit_from_evidence` point at a named existing test to copy from; the implementer resolves them by reading, not inventing.
- **Type consistency.** `plan_font_instances(family, data, *, italic, weights)` used identically in T3/T4; `SceneTextFaceAvailability` shape `{bold, italic}` in T6 logic, toolbar, canvas, tests; `sceneTextMarkState` returns `{pressed, disabled, reason}` everywhere; `Summary` field names match between script and test; `LINE_HEIGHT_RATIO_RANGE` defined in T2, imported in T5.
