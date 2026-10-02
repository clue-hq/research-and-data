"""The User-Agent our two automated QA renderers present.

Brandfetch's Logo-API CDN refuses any browser whose User-Agent contains
``HeadlessChrome`` — it answers 302 with ``x-bf-error: automated_traffic``. Both of our
automated QA renderers run headless: the gallery page thumbnail
(``document_thumbnails.web_thumbnail_png``) and the clone-review walk
(``clone_review/browser.py``). So a hotlinked decorative logo renders EMPTY in both, and
the review agent cannot judge the page as a visitor actually sees it.

FOUNDER DECISION (2026-09-02, plan D11): those two renderers present a normal Chrome
User-Agent, behind ``LUMEN_QA_RENDER_UA_OVERRIDE``, which defaults ON. Setting it to ``0``
restores the headless User-Agent — the switch to reach for if the vendor objects.

The vendor's own guidance, quoted so the tradeoff is visible at the site that takes it:
"Programmatic access to logo images is not permitted and may result in rate limiting or
blocking"; "A valid client ID does not exempt a request from the automated_traffic check";
"If your use case needs server-side access or caching, contact us for a custom setup."

**This is for the two QA renderers and nothing else.** Never the editor, never publish,
never ``fragments/isolation.py`` — that module allow-lists routes and must stay closed.
"""

from __future__ import annotations

#: A current desktop Chrome on macOS. The one thing that matters is what it does NOT say.
QA_RENDER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def qa_render_context_kwargs() -> dict[str, str]:
    """`Browser.new_context` kwargs for the QA renderers: the override UA when the
    flag is on, nothing when off."""

    from py_lumen_config import settings  # read at CALL time so a flag flip is honoured

    return {"user_agent": QA_RENDER_USER_AGENT} if settings.lumen_qa_render_ua_override else {}
