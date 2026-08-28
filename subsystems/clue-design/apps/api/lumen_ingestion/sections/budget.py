"""What one page's clone may WEIGH, and what happens when it weighs more (clone-fidelity F3.4).

Why this module exists
----------------------
The F2 acceptance re-walk measured the two things nothing was bounding. Cloning stripe.com's
homepage minted **1,353,811 bytes of scoped CSS** across ten fragments (172 KB in the heaviest
one) and **5,981,943 bytes of preview PNGs** at rest, one of them 1.9 MB. Nothing counted either,
so nothing said either.

**The ceilings are now 5 GiB, by founder ruling (2026-08-28)** — see
:data:`_FOUNDER_RULING_BYTES`. Storage is not the constraint; quality is the point. So in
practice nothing a real page produces is refused, degraded or even warned about on byte grounds,
and this module's job today is to COUNT and to be ready. That is deliberate: the machinery below
is the thing that has to keep working, because the day a ceiling matters is the day somebody
lowers one, and a budget nobody exercised by then is a budget nobody can trust.

Two budgets each, and they answer different questions. A PER-FRAGMENT budget catches one
pathological section; a PER-PAGE budget catches the page that is heavy everywhere without any one
section being remarkable — stripe is the second shape, and a per-fragment limit alone would have
stayed silent about it forever.

The outcomes are deliberately different, and neither is a silent cap
-------------------------------------------------------------------
Standing rule, from the cross-cutting register: **no silent caps.** Every budget here reports the
number it measured, the budget it measured against, and what it DID about it. (At the ruling's
ceilings none of these fires on real input — they are described in the present tense because the
code is present, and they are all exercised by tests that inject small limits.)

* **CSS is WARNED about, never truncated.** The scoped stylesheet is what makes a cloned section
  look like itself; dropping rules out of it produces a fragment that renders subtly wrong and
  says nothing, which is the exact failure mode this phase exists to remove. The honest answer to
  "this clone carries 1.3 MB of CSS" is to say so with the number, and let a human decide whether
  the site is worth it.
* **A preview is DEGRADED, and only then refused.** A preview is a thumbnail, not a rendition:
  making it narrower loses nothing but pixels nobody was going to look at, so an over-budget
  preview is re-encoded smaller before anything is given up. Only when it will not fit even at
  :data:`MIN_PREVIEW_WIDTH` is it dropped — and since F3.2 that is recoverable too, because an
  isolation render (ruling P-7) photographs any fragment from its own bytes on demand.

The numbers are POLICY, and the limits are injectable
-----------------------------------------------------
The ceilings are a founder decision (quality over storage), not an engineering estimate — the
measurements they dwarf are kept beside them so a future retune can see what real pages actually
weigh. Every limit also lives on :class:`PageWeight` as a field, so a caller — a test today, a
per-tenant policy later — hands in its own numbers instead of editing a global.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: THE NUMBER, for every byte budget in this module (FOUNDER RULING, 2026-08-28).
#:
#: In the founder's words: *storage of high-quality images and assets is not a concern right now;
#: quality is all that matters.* So every byte budget below is 5 GiB, and none of them fires on
#: anything a real page could produce — the heaviest capture this project has taken is four
#: orders of magnitude under it (see the measurements kept beside each constant).
#:
#: **This is deliberate policy, not an engineering estimate**, and the distinction matters to
#: whoever retunes it next: the numbers are not a guess at what a page "should" weigh, they are a
#: decision that fidelity outranks storage. The MACHINERY is unchanged and stays exercised —
#: every budget still counts, still reports the number and the budget it measured against, and
#: still names its outcome; a disabled dead-height check still says so. What changed is only how
#: far away the ceiling is.
_FOUNDER_RULING_BYTES = 5 * 1024**3

#: How many bytes of scoped CSS one FRAGMENT may carry. Founder ruling above; for scale, the
#: heaviest cloned section this project has measured is stripe.com's at 172,197 bytes.
MAX_FRAGMENT_CSS_BYTES = _FOUNDER_RULING_BYTES

#: How many bytes of scoped CSS one PAGE's fragments may carry between them. Founder ruling
#: above; for scale, stripe.com's homepage measured 1,353,811 across ten fragments and
#: insighthealth's 417,586 across nine. This is the budget that would have caught the F2 finding,
#: because no single stripe fragment was remarkable — the page was heavy everywhere.
MAX_PAGE_CSS_BYTES = _FOUNDER_RULING_BYTES

#: How many bytes one preview PNG may weigh. Founder ruling above. The F2 re-walk's largest crops
#: were 1,036,801 (insighthealth) and 1,921,123 (stripe) bytes, and an earlier draft of this
#: module treated those numbers as the defect and set the budget below them so they would be
#: re-encoded smaller. The ruling reverses that judgement: a big picture of a real section is
#: quality, not waste, and the crop ships at the size it was taken.
MAX_PREVIEW_BYTES = _FOUNDER_RULING_BYTES

#: The narrowest a preview may be re-encoded at in pursuit of the byte budget. Unreachable in
#: practice at the ruling's ceiling — nothing is re-encoded — and kept because the degrade path
#: is kept.
MIN_PREVIEW_WIDTH = 320

#: How many bytes of preview PNG one PAGE may put at rest. Founder ruling above; the heaviest
#: real page measured under 6 MB across ten previews.
MAX_PAGE_PREVIEW_BYTES = _FOUNDER_RULING_BYTES

#: The one code every budget in this module pays. One code, one meaning: "a clone weighed more
#: than the budget for it" — which budget, what it measured, and what was done are structured
#: keys, so a consumer never parses the sentence.
MINT_BUDGET_CODE = "LUMI0537"

#: The three things a budget may do, spelled once so a consumer can switch on them.
OUTCOME_WARNED = "warned"
OUTCOME_DEGRADED = "degraded"
OUTCOME_REFUSED = "refused"


@dataclass
class PageWeight:
    """One page's running totals, so the per-page budgets are answerable at all.

    Mutable and threaded through the mint of a single page — ``mint_sections`` is called once per
    captured page, so the object's life is exactly the scope of the budget it accounts for. The
    ``*_reported`` flags exist because a per-page budget is one fact about the page: once it has
    been said, saying it again per section would bury the per-section lines that matter.
    """

    #: ALL FOUR limits, carried on the object rather than read off this module's globals — the
    #: per-fragment ones as well as the per-page ones, so there is exactly ONE place a limit is
    #: read from and exactly one seam to inject through.
    #:
    #: That seam is what keeps the machinery honest under the founder's 5 GiB ruling: at those
    #: ceilings no real page can exercise a single budget branch, so the tests hand in small
    #: limits and drive every path — warn, degrade, refuse, and the dead-height check that a
    #: refusal switches off. A test that instead reached in and rewrote a module constant would
    #: be testing a global, and would silently stop testing anything the day the production
    #: numbers moved. They moved.
    fragment_css_limit: int = MAX_FRAGMENT_CSS_BYTES
    page_css_limit: int = MAX_PAGE_CSS_BYTES
    preview_limit: int = MAX_PREVIEW_BYTES
    page_preview_limit: int = MAX_PAGE_PREVIEW_BYTES
    css_bytes: int = 0
    preview_bytes: int = 0
    fragment_count: int = 0
    css_reported: bool = False

    def fragment_css_fits(self, size: int) -> bool:
        """May one fragment carry this much scoped CSS?"""
        return size <= self.fragment_css_limit

    def add_css(self, size: int) -> bool:
        """Record a fragment's CSS. Returns ``True`` the FIRST time the page goes over budget."""
        self.css_bytes += size
        self.fragment_count += 1
        if self.css_bytes <= self.page_css_limit or self.css_reported:
            return False
        self.css_reported = True
        return True

    def preview_fits(self, size: int) -> bool:
        """May a preview of this size still be stored on this page?"""
        return self.preview_bytes + size <= self.page_preview_limit

    def add_preview(self, size: int) -> None:
        self.preview_bytes += size


def budget_diagnostic(
    *,
    budget: str,
    limit: int,
    measured: int,
    outcome: str,
    message: str,
    severity: str = "warning",
    **extra: Any,
) -> dict[str, Any]:
    """The loud diagnostic every budget in this module pays.

    ``budget`` names the limit in human words, ``limit`` is its value, ``measured`` is what was
    actually counted, and ``outcome`` is one of :data:`OUTCOME_WARNED` / :data:`OUTCOME_DEGRADED`
    / :data:`OUTCOME_REFUSED` — because "we noticed" and "we dropped it" are different facts and
    a reader must never have to infer which one happened from the wording.
    """
    return {
        "code": MINT_BUDGET_CODE,
        "severity": severity,
        "message": message,
        "budget": budget,
        "limit": limit,
        "measured": measured,
        "outcome": outcome,
        **extra,
    }


__all__ = [
    "MAX_FRAGMENT_CSS_BYTES",
    "MAX_PAGE_CSS_BYTES",
    "MAX_PAGE_PREVIEW_BYTES",
    "MAX_PREVIEW_BYTES",
    "MIN_PREVIEW_WIDTH",
    "MINT_BUDGET_CODE",
    "OUTCOME_DEGRADED",
    "OUTCOME_REFUSED",
    "OUTCOME_WARNED",
    "PageWeight",
    "budget_diagnostic",
]
