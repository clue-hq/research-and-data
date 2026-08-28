"""The browser half of the behavioural walk (F3.3). Playwright lives here and nowhere else.

Split out of :mod:`lumen_api.clone_review.walk` so that module — the plan, the probe, the shapes
and every judgement over them — can be imported and exercised on a machine with no chromium at
all. That is the F3.2 isolation-render seam again, and the reason it is worth repeating: the
walk's value is entirely in what it REFUSES to claim, and a refusal you can only reach by
launching a browser is a refusal nobody tests.

**No fabrication, ever.** Each of the six classes is attempted independently and each one that
fails comes back abstained with a code. The one thing that raises is a browser that will not
open at all, because a walk with no browser is not a partial walk — it is no walk.

**Every pass is a fresh page on one browser.** A viewport change mid-page re-lays-out a document
that has already had its transitions run, which is not the state a reader arrives in; the phone
pass has to be a phone from the first paint. The browser itself is shared across the passes, so
the cost is one launch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from py_lumen_obs import get_logger

from .walk import (
    DOCUMENT_HEIGHT_SCRIPT,
    SECTION_PROBE_SCRIPT,
    WALK_CLASS_CONSOLE,
    WALK_CLASS_FULL_PAGE,
    WALK_CLASS_HEIGHT_COLLAPSE,
    WALK_CLASS_MOBILE,
    WALK_CLASS_REDUCED_MOTION,
    WALK_CLASS_LABELS,
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


def run_walk(page_html: str, plan: WalkPlan, *, output_dir: Path) -> BehaviouralWalk:
    """Open one browser, make the six observations, close it. See the module docstring."""
    from playwright.sync_api import sync_playwright

    output_dir.mkdir(parents=True, exist_ok=True)
    console: list[ConsoleEntry] = []
    probes = [
        {"fragment_id": probe.fragment_id, "selector": probe.selector}
        for probe in plan.sections
    ]

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
            desktop = _desktop_pass(browser, page_html, plan, probes, console, output_dir)
            mobile = _mobile_pass(browser, page_html, plan, probes, console, output_dir)
            reduced = _reduced_motion_pass(
                browser, page_html, plan, probes, console, output_dir, desktop
            )
        finally:
            browser.close()

    observations = (
        desktop.full_page,
        desktop.scroll_through,
        mobile,
        WalkObservation(
            walk_class=WALK_CLASS_CONSOLE,
            made=True,
            console=tuple(console),
            notes={"passes": ["desktop", "mobile", "reduced_motion"]},
        ),
        desktop.height_collapse,
        reduced,
    )
    return BehaviouralWalk(observations=observations, plan=plan)


class _DesktopResult:
    """The three observations the desktop pass produces, plus what the next pass needs."""

    def __init__(self) -> None:
        self.full_page: WalkObservation = abstained(WALK_CLASS_FULL_PAGE, "not_attempted")
        self.scroll_through: WalkObservation = abstained(
            WALK_CLASS_SCROLL_THROUGH, "not_attempted"
        )
        self.height_collapse: WalkObservation = abstained(
            WALK_CLASS_HEIGHT_COLLAPSE, "not_attempted"
        )
        self.document_height: float | None = None


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
    # page threw, which is the strongest console signal there is.
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
) -> _DesktopResult:
    result = _DesktopResult()
    try:
        page = _open(browser, html, plan.desktop, console, pass_name="desktop")
    except Exception as error:  # noqa: BLE001
        because = _because(error)
        result.full_page = abstained(WALK_CLASS_FULL_PAGE, because)
        result.scroll_through = abstained(WALK_CLASS_SCROLL_THROUGH, because)
        result.height_collapse = abstained(WALK_CLASS_HEIGHT_COLLAPSE, because)
        return result
    try:
        page.wait_for_timeout(plan.settle_ms)
        geometry = _geometry(page)
        result.document_height = geometry.get("height")

        result.full_page = _try(
            WALK_CLASS_FULL_PAGE,
            lambda: _full_page(page, plan, output_dir, geometry),
        )
        result.scroll_through = _try(
            WALK_CLASS_SCROLL_THROUGH,
            lambda: _scroll_through(page, plan, output_dir, geometry),
        )
        result.height_collapse = _try(
            WALK_CLASS_HEIGHT_COLLAPSE,
            lambda: _height_collapse(page, plan, probes),
        )
    finally:
        page.context.close()
    return result


def _full_page(page: Any, plan: WalkPlan, output_dir: Path, geometry: dict) -> WalkObservation:
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
        notes={"document_height_px": geometry.get("height")},
    )


def _scroll_through(
    page: Any, plan: WalkPlan, output_dir: Path, geometry: dict
) -> WalkObservation:
    document_height = float(geometry.get("height") or 0.0)
    scrollable = max(0.0, document_height - plan.desktop.height)
    shots: list[CaptureShot] = []
    for stop in plan.scroll_stops:
        offset = scrollable * stop
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
        notes={"scrollable_px": round(scrollable, 1)},
    )


def _height_collapse(page: Any, plan: WalkPlan, probes: list[dict[str, str]]) -> WalkObservation:
    raw = page.evaluate(SECTION_PROBE_SCRIPT, probes) if probes else []
    return WalkObservation(
        walk_class=WALK_CLASS_HEIGHT_COLLAPSE,
        made=True,
        measurements=measurements_from_probe(raw, viewport=plan.desktop.name),
        notes={"sections_probed": len(probes)},
    )


def _mobile_pass(
    browser: Any,
    html: str,
    plan: WalkPlan,
    probes: list[dict[str, str]],
    console: list[ConsoleEntry],
    output_dir: Path,
) -> WalkObservation:
    try:
        page = _open(browser, html, plan.mobile, console, pass_name="mobile")
    except Exception as error:  # noqa: BLE001
        return abstained(WALK_CLASS_MOBILE, _because(error))
    try:
        page.wait_for_timeout(plan.settle_ms)
        geometry = _geometry(page)
        destination = output_dir / "walk_mobile.png"
        page.screenshot(path=str(destination), full_page=True)
        raw = page.evaluate(SECTION_PROBE_SCRIPT, probes) if probes else []
        return WalkObservation(
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
                "viewport_width": plan.mobile.width,
                "document_scroll_width_px": geometry.get("width"),
            },
        )
    except Exception as error:  # noqa: BLE001
        return abstained(WALK_CLASS_MOBILE, _because(error))
    finally:
        page.context.close()


def _reduced_motion_pass(
    browser: Any,
    html: str,
    plan: WalkPlan,
    probes: list[dict[str, str]],
    console: list[ConsoleEntry],
    output_dir: Path,
    desktop: _DesktopResult,
) -> WalkObservation:
    try:
        page = _open(
            browser,
            html,
            plan.desktop,
            console,
            pass_name="reduced_motion",
            reduced_motion=True,
        )
    except Exception as error:  # noqa: BLE001
        return abstained(WALK_CLASS_REDUCED_MOTION, _because(error))
    try:
        page.wait_for_timeout(plan.settle_ms)
        geometry = _geometry(page)
        destination = output_dir / "walk_reduced_motion.png"
        page.screenshot(path=str(destination), full_page=True)
        raw = page.evaluate(SECTION_PROBE_SCRIPT, probes) if probes else []
        notes: dict[str, Any] = {"document_height_px": geometry.get("height")}
        if desktop.document_height:
            notes["motion_document_height_px"] = desktop.document_height
        return WalkObservation(
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
        return abstained(WALK_CLASS_REDUCED_MOTION, _because(error))
    finally:
        page.context.close()


def _geometry(page: Any) -> dict:
    try:
        value = page.evaluate(DOCUMENT_HEIGHT_SCRIPT)
    except Exception:  # noqa: BLE001 — geometry is a note, never the reason a pass fails
        return {}
    return value if isinstance(value, dict) else {}


def _try(walk_class: str, make) -> WalkObservation:
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


__all__ = ["BROWSER_LAUNCH_FAILED_CODE", "run_walk"]
