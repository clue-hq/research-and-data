"""The browser half of the behavioural walk (F3.3). Playwright lives here and nowhere else.

Split out of :mod:`lumen_api.clone_review.walk` so that module — the plan, the probe, the shapes
and every judgement over them — can be imported and exercised on a machine with no chromium at
all. That is the F3.2 isolation-render seam again, and the reason it is worth repeating: the
walk's value is entirely in what it REFUSES to claim, and a refusal you can only reach by
launching a browser is a refusal nobody tests.

**The browser is INJECTED** (review finding I3). :func:`run_walk` takes a factory returning a
context-managed browser handle; the default one launches chromium. Most of what lives in this
file is not browser logic at all — it is which passes opened, how the six observations are
assembled from them, how a console line is levelled and blamed, and the scroll arithmetic — and
before the seam existed none of it could be reached by a test. The bug that taught the lesson
(C1: the console class reporting "observed, no errors" for a page nobody opened) sat here for a
whole review round precisely because nothing could call this function.

**No fabrication, ever.** Each of the six classes is attempted independently and each one that
fails comes back abstained with a code. The console class is now built only from the passes that
actually opened a page, and abstains when none did. The one thing that raises is a browser that
will not open at all, because a walk with no browser is not a partial walk — it is no walk.

**Every pass is a fresh context.** A viewport change mid-page re-lays-out a document that has
already had its transitions run, which is not the state a reader arrives in; the phone pass has
to be a phone from the first paint. The browser itself is shared across the passes, so the cost
is one launch.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from py_lumen_obs import get_logger

from lumen_api.capture_readiness import prepare_capture_media
from lumen_api.qa_render_ua import qa_render_context_kwargs

from .walk import (
    DOCUMENT_HEIGHT_SCRIPT,
    STYLES_READY_TIMEOUT_MS,
    SECTION_PROBE_SCRIPT,
    STYLES_READY_SCRIPT,
    WALK_CLASS_CONSOLE,
    WALK_CLASS_FULL_PAGE,
    WALK_CLASS_HEIGHT_COLLAPSE,
    WALK_CLASS_LABELS,
    WALK_CLASS_MOBILE,
    WALK_CLASS_REDUCED_MOTION,
    WALK_CLASS_SCROLL_THROUGH,
    WALK_TIMEOUT_MS,
    BehaviouralWalk,
    CaptureShot,
    CloneReviewRefused,
    ConsoleEntry,
    ViewportSpec,
    WalkObservation,
    WalkPlan,
    abstained,
    measurements_from_probe,
)

logger = get_logger("lumen_api.clone_review.browser")

BROWSER_LAUNCH_FAILED_CODE = "review.browser_launch_failed"

#: The `because` code the console class abstains with when not one pass opened a page.
CONSOLE_NO_PASS_OPENED = "no_pass_opened"

#: The names the three passes are recorded under, in walk order. (The readiness deadline these
#: passes wait to lives beside its predicate: `walk.STYLES_READY_TIMEOUT_MS`.)
PASS_DESKTOP = "desktop"
PASS_MOBILE = "mobile"
PASS_REDUCED_MOTION = "reduced_motion"


@contextmanager
def chromium_browser() -> Iterator[Any]:
    """The default browser: one headless chromium, closed on the way out.

    A launch that fails is a typed refusal rather than an exception, because "this host has the
    package but not the browser binary" is a deployment fact an operator can act on.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as error:  # noqa: BLE001
            raise CloneReviewRefused(
                BROWSER_LAUNCH_FAILED_CODE,
                f"a browser is installed but would not start: {error}. Nothing was walked, so "
                "nothing is reported — run `playwright install chromium` on this host",
            ) from error
        try:
            yield browser
        finally:
            browser.close()


@dataclass
class _PassOutcome:
    """What one pass produced, and — the part C1 turned on — whether it ever opened a page."""

    opened: bool = False
    observations: dict[str, WalkObservation] = field(default_factory=dict)
    document_height: float | None = None
    styles_ready: bool | None = None
    media_ready: bool = False


def run_walk(
    page_html: str,
    plan: WalkPlan,
    *,
    output_dir: Path,
    browser_factory: Callable[[], Any] = chromium_browser,
) -> BehaviouralWalk:
    """Open one browser, make the six observations, close it. See the module docstring.

    ``browser_factory`` returns a context manager yielding something with ``new_context``. The
    default launches chromium; a test passes a fake and exercises everything except chromium.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    console: list[ConsoleEntry] = []
    probes = [
        {"fragment_id": probe.fragment_id, "selector": probe.selector}
        for probe in plan.sections
    ]

    with browser_factory() as browser:
        desktop = _desktop_pass(browser, page_html, plan, probes, console, output_dir)
        mobile = _mobile_pass(browser, page_html, plan, probes, console, output_dir)
        reduced = _reduced_motion_pass(
            browser, page_html, plan, probes, console, output_dir, desktop
        )

    return BehaviouralWalk(
        observations=(
            desktop.observations[WALK_CLASS_FULL_PAGE],
            desktop.observations[WALK_CLASS_SCROLL_THROUGH],
            mobile.observations[WALK_CLASS_MOBILE],
            console_observation(console, (desktop, mobile, reduced)),
            desktop.observations[WALK_CLASS_HEIGHT_COLLAPSE],
            reduced.observations[WALK_CLASS_REDUCED_MOTION],
        ),
        plan=plan,
    )


def console_observation(
    console: list[ConsoleEntry], passes: tuple[_PassOutcome, ...]
) -> WalkObservation:
    """The console class, built from the passes that ACTUALLY opened a page (review finding C1).

    The console is the one class with no pass of its own — it is a side effect of the other three
    — so it was previously assembled unconditionally, and a walk in which chromium launched but
    every `set_content` timed out reported "console observed, zero entries" for a page nobody had
    opened. That is a fabricated clean bill of exactly the kind this module's opening paragraph
    forbids, and a *partial* failure was worse: the note still named a pass that never ran, so a
    phone-only error was silently absent from a "made" observation.

    Now the note lists the real passes, and the class abstains only when there is nothing to
    report at all — no pass opened AND nothing was heard. (Console handlers attach before
    `set_content`, so a pass whose load then timed out can still have put real lines on the
    console; that evidence is kept, named, and carried beside `opened`.)
    """
    order = (PASS_DESKTOP, PASS_MOBILE, PASS_REDUCED_MOTION)
    opened = tuple(name for name, outcome in zip(order, passes) if outcome.opened)
    # The console handlers are attached BEFORE `set_content`, so a pass whose load timed out can
    # already have put real lines on the console (round-2 re-review, breakage #5). Discarding that
    # evidence would be worse than keeping it, and keeping it under a note that does not name the
    # pass makes the two disagree — so the note reports what was actually observed, and `opened`
    # is carried beside it for the passes that also finished.
    heard = {entry.pass_name for entry in console}
    observed = tuple(name for name in order if name in heard or name in opened)
    if not observed:
        return abstained(WALK_CLASS_CONSOLE, CONSOLE_NO_PASS_OPENED)
    return WalkObservation(
        walk_class=WALK_CLASS_CONSOLE,
        made=True,
        console=tuple(console),
        notes={"passes": list(observed), "opened": list(opened)},
    )


def _open(
    browser: Any,
    html: str,
    viewport: ViewportSpec,
    console: list[ConsoleEntry],
    *,
    pass_name: str,
    reduced_motion: bool = False,
) -> Any:
    """One fresh context per pass. A viewport swap mid-page re-lays-out a document whose
    transitions have already run, which is not the state a reader arrives in."""
    context = browser.new_context(
        viewport={"width": viewport.width, "height": viewport.height},
        reduced_motion="reduce" if reduced_motion else "no-preference",
        # A normal Chrome UA when the flag is on — see `qa_render_ua.py`.
        **qa_render_context_kwargs(),
    )
    page = context.new_page()
    page.set_default_timeout(WALK_TIMEOUT_MS)
    page.on("console", lambda message: _record_console(message, console, pass_name))
    page.on("pageerror", lambda error: _record_page_error(error, console, pass_name))
    page.set_content(html, wait_until="load")
    return page


def _record_console(message: Any, console: list[ConsoleEntry], pass_name: str) -> None:
    level = str(getattr(message, "type", "") or "")
    if level not in ("error", "warning"):
        return
    location = getattr(message, "location", None) or {}
    console.append(
        ConsoleEntry(
            level=level,
            text=str(getattr(message, "text", "") or "")[:500],
            url=str(location.get("url") or "") or None,
            line=location.get("lineNumber"),
            pass_name=pass_name,
        )
    )


def _record_page_error(error: Any, console: list[ConsoleEntry], pass_name: str) -> None:
    # An uncaught exception is reported at `error` severity with no location of its own — the
    # page threw, which is the strongest console signal there is. It is blamed on the SHELL by
    # `ConsoleEntry.source` (no url), which on this page is correct by construction: a cloned
    # band carries no scripts, so the only code that can throw here is ours.
    console.append(
        ConsoleEntry(
            level="error",
            text=f"uncaught: {error}"[:500],
            url=None,
            line=None,
            pass_name=pass_name,
        )
    )


def _desktop_pass(
    browser: Any,
    html: str,
    plan: WalkPlan,
    probes: list[dict[str, str]],
    console: list[ConsoleEntry],
    output_dir: Path,
) -> _PassOutcome:
    outcome = _PassOutcome()
    try:
        page = _open(browser, html, plan.desktop, console, pass_name=PASS_DESKTOP)
    except Exception as error:  # noqa: BLE001
        because = _because(error)
        for walk_class in (
            WALK_CLASS_FULL_PAGE,
            WALK_CLASS_SCROLL_THROUGH,
            WALK_CLASS_HEIGHT_COLLAPSE,
        ):
            outcome.observations[walk_class] = abstained(walk_class, because)
        return outcome
    outcome.opened = True
    try:
        page.wait_for_timeout(plan.settle_ms)
        # Readiness FIRST, geometry second (round-2 re-review, breakage #1): the scroll plan and
        # the height notes must describe the COMPILED page. Read the other way round, a slow JIT
        # hands `_scroll_through` the unstyled document's height — several captions, one clamped
        # position (the M3 defect back again), or a page whose bottom is never photographed.
        outcome.styles_ready = _styles_ready(page)
        media = prepare_capture_media(page)
        outcome.media_ready = media.get("settled") is True
        geometry = _geometry(page)
        outcome.document_height = geometry.get("height")

        outcome.observations[WALK_CLASS_FULL_PAGE] = _try(
            WALK_CLASS_FULL_PAGE,
            lambda: _full_page(page, plan, output_dir, geometry, media),
        )
        outcome.observations[WALK_CLASS_SCROLL_THROUGH] = _try(
            WALK_CLASS_SCROLL_THROUGH,
            lambda: _scroll_through(page, plan, output_dir, geometry),
        )
        outcome.observations[WALK_CLASS_HEIGHT_COLLAPSE] = _try(
            WALK_CLASS_HEIGHT_COLLAPSE,
            lambda: _height_collapse(page, plan, probes, outcome.styles_ready, media),
        )
    finally:
        page.context.close()
    return outcome


def _full_page(
    page: Any, plan: WalkPlan, output_dir: Path, geometry: dict, media: dict
) -> WalkObservation:
    destination = output_dir / "walk_full_page.png"
    page.screenshot(path=str(destination), full_page=True)
    return WalkObservation(
        walk_class=WALK_CLASS_FULL_PAGE,
        made=True,
        shots=(
            CaptureShot(
                walk_class=WALK_CLASS_FULL_PAGE,
                label=WALK_CLASS_LABELS[WALK_CLASS_FULL_PAGE],
                path=str(destination),
                viewport_width=plan.desktop.width,
            ),
        ),
        notes={"document_height_px": geometry.get("height"), "media_readiness": media},
    )


def scroll_offsets(
    document_height: float, viewport_height: int, stops: tuple[float, ...]
) -> tuple[tuple[float, float], ...]:
    """``((stop, offset), …)`` — the DISTINCT positions this page actually has.

    A page shorter than the viewport has exactly one position, and photographing it five times
    under the captions "25%", "50%", "75%" and "100%" would claim four states the page does not
    have (review finding M3). Deduped on the offset, so a short page yields one honest capture
    and a long one yields all five.
    """
    scrollable = max(0.0, document_height - float(viewport_height))
    seen: dict[float, float] = {}
    for stop in stops:
        offset = round(scrollable * stop, 1)
        seen.setdefault(offset, stop)
    return tuple((stop, offset) for offset, stop in seen.items())


def _scroll_through(
    page: Any, plan: WalkPlan, output_dir: Path, geometry: dict
) -> WalkObservation:
    document_height = float(geometry.get("height") or 0.0)
    positions = scroll_offsets(document_height, plan.desktop.height, plan.scroll_stops)
    shots: list[CaptureShot] = []
    for stop, offset in positions:
        page.evaluate("(y) => window.scrollTo(0, y)", offset)
        page.wait_for_timeout(plan.settle_ms)
        destination = output_dir / f"walk_scroll_{int(round(stop * 100)):03d}.png"
        page.screenshot(path=str(destination), full_page=False)
        shots.append(
            CaptureShot(
                walk_class=WALK_CLASS_SCROLL_THROUGH,
                label=f"scroll position {int(round(stop * 100))}%",
                path=str(destination),
                viewport_width=plan.desktop.width,
                scroll_fraction=stop,
            )
        )
    page.evaluate("() => window.scrollTo(0, 0)")
    return WalkObservation(
        walk_class=WALK_CLASS_SCROLL_THROUGH,
        made=True,
        shots=tuple(shots),
        notes={
            "scrollable_px": round(max(0.0, document_height - plan.desktop.height), 1),
            "distinct_positions": len(positions),
        },
    )


def _height_collapse(
    page: Any, plan: WalkPlan, probes: list[dict[str, str]],
    styles_ready: bool | None, media: dict,
) -> WalkObservation:
    raw = page.evaluate(SECTION_PROBE_SCRIPT, probes) if probes else []
    return WalkObservation(
        walk_class=WALK_CLASS_HEIGHT_COLLAPSE,
        made=True,
        measurements=measurements_from_probe(raw, viewport=plan.desktop.name),
        notes={
            "sections_probed": len(probes), "styles_ready": styles_ready,
            "media_readiness": media,
        },
    )


def _mobile_pass(
    browser: Any,
    html: str,
    plan: WalkPlan,
    probes: list[dict[str, str]],
    console: list[ConsoleEntry],
    output_dir: Path,
) -> _PassOutcome:
    outcome = _PassOutcome()
    try:
        page = _open(browser, html, plan.mobile, console, pass_name=PASS_MOBILE)
    except Exception as error:  # noqa: BLE001
        outcome.observations[WALK_CLASS_MOBILE] = abstained(
            WALK_CLASS_MOBILE, _because(error)
        )
        return outcome
    outcome.opened = True
    try:
        page.wait_for_timeout(plan.settle_ms)
        # Same order as the desktop pass: the width note must be the compiled page's.
        outcome.styles_ready = _styles_ready(page)
        media = prepare_capture_media(page)
        outcome.media_ready = media.get("settled") is True
        geometry = _geometry(page)
        destination = output_dir / "walk_mobile.png"
        page.screenshot(path=str(destination), full_page=True)
        raw = page.evaluate(SECTION_PROBE_SCRIPT, probes) if probes else []
        outcome.observations[WALK_CLASS_MOBILE] = WalkObservation(
            walk_class=WALK_CLASS_MOBILE,
            made=True,
            shots=(
                CaptureShot(
                    walk_class=WALK_CLASS_MOBILE,
                    label=WALK_CLASS_LABELS[WALK_CLASS_MOBILE],
                    path=str(destination),
                    viewport_width=plan.mobile.width,
                ),
            ),
            measurements=measurements_from_probe(raw, viewport=plan.mobile.name),
            notes={
                "media_readiness": media,
                "viewport_width": plan.mobile.width,
                "document_scroll_width_px": geometry.get("width"),
                "styles_ready": outcome.styles_ready,
            },
        )
    except Exception as error:  # noqa: BLE001
        outcome.observations[WALK_CLASS_MOBILE] = abstained(
            WALK_CLASS_MOBILE, _because(error)
        )
    finally:
        page.context.close()
    return outcome


def _reduced_motion_pass(
    browser: Any,
    html: str,
    plan: WalkPlan,
    probes: list[dict[str, str]],
    console: list[ConsoleEntry],
    output_dir: Path,
    desktop: _PassOutcome,
) -> _PassOutcome:
    outcome = _PassOutcome()
    try:
        page = _open(
            browser,
            html,
            plan.desktop,
            console,
            pass_name=PASS_REDUCED_MOTION,
            reduced_motion=True,
        )
    except Exception as error:  # noqa: BLE001
        outcome.observations[WALK_CLASS_REDUCED_MOTION] = abstained(
            WALK_CLASS_REDUCED_MOTION, _because(error)
        )
        return outcome
    outcome.opened = True
    try:
        page.wait_for_timeout(plan.settle_ms)
        # Same order as the other passes — and load-bearing HERE because of what this pass is
        # for: its height is DIVIDED by the desktop's, and the desktop's is post-readiness. One
        # settled height over one unstyled height is a divergence measurement of nothing but the
        # clock (round-3 re-review), so the pair records whether both halves were settled and
        # `reduced_motion_findings` refuses to compare an unsettled pair.
        outcome.styles_ready = _styles_ready(page)
        media = prepare_capture_media(page)
        outcome.media_ready = media.get("settled") is True
        geometry = _geometry(page)
        destination = output_dir / "walk_reduced_motion.png"
        page.screenshot(path=str(destination), full_page=True)
        raw = page.evaluate(SECTION_PROBE_SCRIPT, probes) if probes else []
        notes: dict[str, Any] = {
            "media_readiness": media,
            "document_height_px": geometry.get("height"),
            "styles_ready": outcome.styles_ready,
            "heights_settled": (
                desktop.styles_ready is True and outcome.styles_ready is True
                and desktop.media_ready and outcome.media_ready
            ),
        }
        if desktop.document_height:
            notes["motion_document_height_px"] = desktop.document_height
        outcome.observations[WALK_CLASS_REDUCED_MOTION] = WalkObservation(
            walk_class=WALK_CLASS_REDUCED_MOTION,
            made=True,
            shots=(
                CaptureShot(
                    walk_class=WALK_CLASS_REDUCED_MOTION,
                    label=WALK_CLASS_LABELS[WALK_CLASS_REDUCED_MOTION],
                    path=str(destination),
                    viewport_width=plan.desktop.width,
                ),
            ),
            measurements=measurements_from_probe(raw, viewport=plan.desktop.name),
            notes=notes,
        )
    except Exception as error:  # noqa: BLE001
        outcome.observations[WALK_CLASS_REDUCED_MOTION] = abstained(
            WALK_CLASS_REDUCED_MOTION, _because(error)
        )
    finally:
        page.context.close()
    return outcome


def _styles_ready(page: Any, *, timeout_ms: int = STYLES_READY_TIMEOUT_MS) -> bool | None:
    """WAIT for the preview shell's Tailwind JIT to produce output. Tri-state (ruling R19-1).

    **Waited for, not sampled** (round-2 re-review, breakage #2). The first version read the
    predicate once, immediately after the 400ms settle — which is a deterministic signal read
    after a sleep, not the deterministic signal the ruling asked for. A JIT slower than 400ms then
    made the gate permanently advice-only AND left the advice itself false: `broken_clones` still
    carried `mobile_unusable` for healthy bands, under a hint telling the agent to re-run, which a
    systematically slow compile can never satisfy.

    So this polls to a bounded deadline. A page that becomes ready inside it produces measurements
    that are TRUE, not merely unwritable. A page that does not gets one honest final sample and
    then ``False``/``None`` — unsettled — which costs the deadline once per probe pass and is the
    price of never writing a marker off an unstyled page.

    ``None`` means the check itself could not run, which is not the same as "no" and is certainly
    not "yes".
    """
    waiter = getattr(page, "wait_for_function", None)
    if waiter is not None:
        try:
            waiter(STYLES_READY_SCRIPT, timeout=timeout_ms)
            return True
        except Exception:  # noqa: BLE001 — a timeout is an answer, not a failure
            pass
    try:
        value = page.evaluate(STYLES_READY_SCRIPT)
    except Exception:  # noqa: BLE001
        return None
    return value if isinstance(value, bool) else None


def _geometry(page: Any) -> dict:
    try:
        value = page.evaluate(DOCUMENT_HEIGHT_SCRIPT)
    except Exception:  # noqa: BLE001 — geometry is a note, never the reason a pass fails
        return {}
    return value if isinstance(value, dict) else {}


def _try(walk_class: str, make: Callable[[], WalkObservation]) -> WalkObservation:
    try:
        return make()
    except Exception as error:  # noqa: BLE001 — one class abstains; the pass continues
        logger.warning(
            "clone_review_observation_failed",
            walk_class=walk_class,
            error=f"{type(error).__name__}: {error}",
        )
        return abstained(walk_class, _because(error))


def _because(error: Exception) -> str:
    """A short, stable code for why a class could not be observed.

    Deliberately coarse: the exception text is in the log, and a `because` that varied with a
    browser's wording would be a code nothing could branch on.
    """
    name = type(error).__name__
    if "Timeout" in name:
        return "timed_out"
    return "browser_error"


__all__ = [
    "BROWSER_LAUNCH_FAILED_CODE",
    "CONSOLE_NO_PASS_OPENED",
    "PASS_DESKTOP",
    "PASS_MOBILE",
    "PASS_REDUCED_MOTION",
    "chromium_browser",
    "console_observation",
    "run_walk",
    "scroll_offsets",
]
