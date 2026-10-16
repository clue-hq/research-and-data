"""Trial-only prompt changes for the website deepagent.

Each override is derived from the platform's current text by an exact replacement, so the
trial prompt differs from production only where these lines say, and a platform edit to the
surrounding text fails loudly here instead of being silently dropped.
"""

from __future__ import annotations

ACCOUNT_EVIDENCE_OLD = """Before you write any words a visitor will see, read
/.deepagent/skills/conversion-copywriting/references/copy-craft.md in full, and for a
named account also /.deepagent/skills/web-account-personalization/references/account-argument.md."""

ACCOUNT_EVIDENCE_NEW = """For a page for one named account, read
/.deepagent/skills/account-page-copy/SKILL.md in full before planning (and its worked example
when it is present). Write its message plan at the top of plan.md before your first build
tool, read the message plan again before writing each section's words, and run its final
check before finalizing. For any other page, read
/.deepagent/skills/conversion-copywriting/references/copy-craft.md in full before writing
words a visitor will see."""

ROUTING_OLD = """For account/contact/event personalization: web-account-personalization; for writing
copy: conversion-copywriting."""

ROUTING_NEW = """For a page for one named account: account-page-copy (message plan, words, final
check). For account/contact/event personalization: web-account-personalization; for writing
copy on other pages: conversion-copywriting."""

WEB_SEARCH_DESCRIPTION = """Search the open web and read back what it found: a short written answer, then up to
ten results with title, URL, date and highlighted passages (the `rendered` field is the
text to read). The account reads and the seller's files under seller/ come first, every time.
Use this for two things. (1) The seller's own published case studies, customer stories and
studies: search with include_domains set to the seller's domain, then open the page with
fetch_page before you use any number or quote from it. (2) The brief's subject when the
platform has nothing on it — an event the seller is running, a workshop, a topic outside its
products. What it returns is text you may use in the design now; it is not a claim, it is not
verified, and it must not be presented as research the platform did."""


def _replace_once(text: str, old: str, new: str, name: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"trial override for {name} no longer matches the platform text")
    return text.replace(old, new)


def apply() -> None:
    """Patch the prompt constants and the web_search description in this process only."""
    from lumen_agent import harness_web, prompts_web

    prompts_web.WEB_ACCOUNT_EVIDENCE = _replace_once(
        prompts_web.WEB_ACCOUNT_EVIDENCE, ACCOUNT_EVIDENCE_OLD, ACCOUNT_EVIDENCE_NEW,
        "WEB_ACCOUNT_EVIDENCE",
    )
    prompts_web.WEB_SKILL_ROUTING = _replace_once(
        prompts_web.WEB_SKILL_ROUTING, ROUTING_OLD, ROUTING_NEW, "WEB_SKILL_ROUTING"
    )

    original = harness_web.make_platform_read_tools

    def make_platform_read_tools(tools, reads):
        made = original(tools, reads)
        for item in made:
            if getattr(item, "name", None) == "web_search":
                item.description = WEB_SEARCH_DESCRIPTION
        return made

    harness_web.make_platform_read_tools = make_platform_read_tools
