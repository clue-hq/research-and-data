"""The asset inliner a Puck site's gallery thumbnail uses.

This module used to build the web and site PDF exports. Founder ruling 2026-10-13
removed every ZIP and PDF export of a web page or site (hosting on the platform is
the only delivery), and what is left is the one piece another module still needs:
:func:`inline_asset_store_refs`, which ``site_publish.site_thumbnail_png`` runs
before the hardened capture. The module keeps its name so the lanes merging this
branch find the inliner where they import it from.

Rendered site HTML names its bytes ROOT-RELATIVELY — ``/asset-store/<digest>`` in
``src``, in ``srcset``, in inline ``style`` ``url()`` and inside the stylesheets —
and a page loaded with ``page.set_content`` has no origin, so every one of those
references would resolve against nothing and paint a broken image. The inliner
rewrites each reference into a ``data:`` URI read straight from the blob store
before the html reaches Chromium. A digest with no blob is left exactly as it was
and reported, never raised: a missing picture is a poorer thumbnail, a raised error
is no thumbnail at all.
"""

from __future__ import annotations

import base64
import re
from typing import Callable, Dict, List, Optional, Tuple

from .database import NotFoundError

#: Every way rendered html names a stored asset is this one absolute path with a
#: sha256 after it — `src="/asset-store/<d>"`, a `srcset` candidate, a CSS
#: `url(/asset-store/<d>)` in an inline `style` or in a stylesheet. One pattern
#: therefore covers markup and CSS alike.
_ASSET_STORE_REF = re.compile(r"/asset-store/([0-9a-fA-F]{64})")


def inline_asset_store_refs(
    html: str,
    read_blob: Callable[[str], Tuple[str, bytes]],
    *,
    cache: Optional[Dict[str, Optional[str]]] = None,
) -> Tuple[str, List[str]]:
    """Replace every ``/asset-store/<digest>`` with a ``data:`` URI of its bytes.

    Pure: it reads blobs through the ``read_blob`` it is handed (the blob store's
    ``read_blob``, i.e. ``digest -> (media_type, bytes)``) and touches nothing
    else. A digest that appears more than once is read once.

    Returns ``(html, missing)``. A digest the store does not have is LEFT IN THE
    HTML untouched and named in ``missing`` — a capture that loses one picture is
    still an honest capture, while raising here would turn a dangling asset row
    into a failure for the whole page.

    ``cache`` maps digest -> data URI (``None`` for a known-missing digest) and may be
    shared across calls: the site turn's screenshot port (``site_turn_ports``) inlines
    a page's HTML and then its CSS, for every render the agent asks for, through one
    cache, so a logo on every page is read once per turn. Each call still names in
    ``missing`` every missing digest IT met, cached or not. Passing nothing gives the
    call its own cache (the gallery card).
    """

    resolved: Dict[str, Optional[str]] = {} if cache is None else cache
    missing: List[str] = []

    def data_uri(digest: str) -> Optional[str]:
        if digest not in resolved:
            try:
                media_type, data = read_blob(digest)
            except NotFoundError:
                resolved[digest] = None
            else:
                encoded = base64.b64encode(data).decode("ascii")
                resolved[digest] = f"data:{media_type};base64,{encoded}"
        if resolved[digest] is None and digest not in missing:
            missing.append(digest)
        return resolved[digest]

    def replace(match: "re.Match[str]") -> str:
        # A function replacement, not a template: base64 is `+/=`-safe but a
        # template would still make `\` in a media type a backreference.
        return data_uri(match.group(1)) or match.group(0)

    return _ASSET_STORE_REF.sub(replace, html), missing
