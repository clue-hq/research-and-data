"""What one page's clone may WEIGH, and what happens when it weighs more (clone-fidelity F3.4).

Why this module exists
----------------------
The F2 acceptance re-walk measured the two things nothing was bounding. Cloning stripe.com's
homepage minted **1,353,811 bytes of scoped CSS** across ten fragments (172 KB in the heaviest
one) and **5,981,943 bytes of preview PNGs** at rest, one of them 1.9 MB — for pictures whose
entire job is to be a thumbnail in a picker. Nothing counted either, so nothing said either.

Two budgets each, and they answer different questions. A PER-FRAGMENT budget catches one
pathological section; a PER-PAGE budget catches the page that is heavy everywhere without any one
section being remarkable — stripe is the second shape, and a per-fragment limit alone would have
stayed silent about it forever.

The outcomes are deliberately different, and neither is a silent cap
-------------------------------------------------------------------
Standing rule, from the cross-cutting register: **no silent caps.** Every budget here reports the
number it measured, the budget it measured against, and what it DID about it.

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

The numbers are TUNABLES, not law
---------------------------------
Each is set from the heaviest real measurement this project has taken, with headroom, so a budget
fires on the abnormal rather than on the merely large. They are stated here, once, so retuning
them is one edit and the rationale travels with the number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: How many bytes of scoped CSS one FRAGMENT may carry. stripe.com's heaviest cloned section
#: measured 172,197 bytes; 256 KB leaves half again as much room. A fragment past this is not a
#: heavy page's section, it is a section that matched most of a design system.
MAX_FRAGMENT_CSS_BYTES = 256 * 1024

#: How many bytes of scoped CSS one PAGE's fragments may carry between them. stripe.com's
#: homepage measured 1,353,811; insighthealth's 417,586. 2 MB is half again above the larger.
#: This is the one that would have caught the F2 finding, because no single stripe fragment was
#: remarkable — the page was heavy everywhere.
MAX_PAGE_CSS_BYTES = 2 * 1024 * 1024

#: How many bytes one preview PNG may weigh. Deliberately BELOW what the real captures produced
#: (insighthealth's largest was 1,036,801; stripe's 1,921,123) because those numbers are the
#: defect: a picker thumbnail has no business being a megabyte. Over-budget previews are made
#: smaller, not dropped, so this budget costs pixels rather than pictures.
MAX_PREVIEW_BYTES = 512 * 1024

#: The narrowest a preview may be re-encoded at in pursuit of the byte budget. Below this a
#: thumbnail stops being something a human can recognise a section by, and dropping it and saying
#: so is more honest than keeping a smear.
MIN_PREVIEW_WIDTH = 320

#: How many bytes of preview PNG one PAGE may put at rest. With the per-preview budget above, a
#: page minting the full section cap could still reach 20 MB; the heaviest real page measured
#: under 6 MB BEFORE the per-preview budget existed, and lands far under it after. A page that
#: reaches this is minting an unreasonable number of unreasonable pictures, and the sections past
#: it are minted WITHOUT previews rather than not minted.
MAX_PAGE_PREVIEW_BYTES = 8 * 1024 * 1024

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

    #: The two per-page limits, carried on the object rather than read off this module's globals.
    #: One reader means one place to retune and one place to override, and it keeps the accounting
    #: honest under a caller that wants different numbers (a test, or a future per-tenant policy).
    css_limit: int = MAX_PAGE_CSS_BYTES
    preview_limit: int = MAX_PAGE_PREVIEW_BYTES
    css_bytes: int = 0
    preview_bytes: int = 0
    fragment_count: int = 0
    css_reported: bool = False

    def add_css(self, size: int) -> bool:
        """Record a fragment's CSS. Returns ``True`` the FIRST time the page goes over budget."""
        self.css_bytes += size
        self.fragment_count += 1
        if self.css_bytes <= self.css_limit or self.css_reported:
            return False
        self.css_reported = True
        return True

    def preview_fits(self, size: int) -> bool:
        """May a preview of this size still be stored on this page?"""
        return self.preview_bytes + size <= self.preview_limit

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
