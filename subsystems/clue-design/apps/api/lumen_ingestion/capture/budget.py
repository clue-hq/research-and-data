"""The asset budget — the ONE place a total slurp is allowed to say "no more".

Why this module exists (clone-fidelity F0.2)
--------------------------------------------
Capture used to carry hard caps scattered across two modules: an image-candidate cap of 50
(``imgsrc.IMAGE_CANDIDATE_CAP``, enforced in ``parse._parse_images``) and a CSS-background cap
of 40 (``imgsrc.MAX_BACKGROUND_IMAGES``, enforced inside the URL harvest itself). The second
was **silent** — it truncated the list and nobody ever heard about it — and the first only
whispered (a ``LUMI0504`` at ``info``). Since the F2 clone harvest rewrites a captured
fragment's asset URLs onto our store, an asset we skipped becomes a broken image on a
published page, so a silent skip is the exact failure this phase exists to remove.

Both caps are replaced by one budget, stated here, generous enough that a typical marketing
page never reaches it, and LOUD whenever it does: every drop pays a ``LUMI0514`` naming the
budget that tripped and the URLs it cost.

**What each half can and cannot bound.** The COUNT budget is applied at collection, before a
single request goes out, so it genuinely bounds network fan-out. The BYTE budget can only be
applied after the bodies are in hand — nothing tells us an asset's size before we fetch it —
so it bounds what a snapshot CARRIES (and therefore what is stored, ingested and replayed),
not what was requested. Both are honest about which they are in their diagnostic text.

The describe engine's own candidate cap is a different concern entirely (VLM cost per image,
not capture completeness) and is deliberately untouched by this module.
"""

from __future__ import annotations

#: How many distinct assets one page capture may fetch. A dense marketing page with a
#: srcset-heavy gallery lands around 120-180 candidates once every rung is enumerated; 400
#: leaves room for a page twice that size before anything is dropped.
MAX_ASSET_COUNT = 400

#: How many bytes of asset bodies one page capture may carry. The per-resource caps in
#: ``net.py`` (15 MB an image, 10 MB a font) still apply on top of this; 100 MB is roughly
#: 400 assets averaging 250 KB, i.e. the count budget's worth of unusually heavy assets.
MAX_ASSET_BYTES = 100 * 1024 * 1024

#: The one code every budget drop pays. Warning severity: the ingestion completes, but a
#: human is told exactly what the page referenced and we did not keep.
BUDGET_DIAGNOSTIC_CODE = "LUMI0514"

#: How many dropped URLs the message itself spells out. The full list always rides in the
#: diagnostic's ``dropped`` key — the truncation is for the human-readable line only.
_NAMED_IN_MESSAGE = 8


def budget_diagnostic(*, budget: str, limit: int, dropped: list[str]) -> dict:
    """The loud diagnostic for a budget drop.

    ``budget`` is the human name of the limit that tripped ("asset count" / "asset bytes"),
    ``limit`` its value, and ``dropped`` every URL it cost — carried in full on the
    ``dropped`` key so a consumer never has to parse the message.
    """
    named = ", ".join(dropped[:_NAMED_IN_MESSAGE])
    more = len(dropped) - _NAMED_IN_MESSAGE
    if more > 0:
        named += f", and {more} more"
    return {
        "code": BUDGET_DIAGNOSTIC_CODE,
        "severity": "warning",
        "message": (
            f"{budget} budget of {limit} reached; {len(dropped)} referenced asset(s) "
            f"were not captured: {named}"
        ),
        "budget": budget,
        "limit": limit,
        "dropped": list(dropped),
    }
