"""Staged trial, stage 1: decide the page's message and words in text only.

The script gathers every input itself (no model calls): the brief, the account's overview and
insights, the seller's files, and the visible text and slot names of the seller's cloned
sections. One small model conversation then writes the message plan and every section's words,
with only two tools: web_search (the platform's) and fetch_page (a plain text fetch), for the
seller's published case studies. Its output becomes plan.md for the build stage.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

SKIP_LABELS = ("Iframe is blocked", "Preferences Manage Consent", "Sign up for our newsletter")
SKIP_ROLES = ("nav", "footer")
FETCH_LIMIT = 12_000

SYSTEM = """You write the message and the words of a landing page for one named account.
You are the copy stage of a two-stage run: you decide what the page says and which cloned
sections carry it; a separate build stage pins those sections and applies your words exactly.
You do not build or render anything.

Follow the skill below. Everything you need is in the user message: the brief, the account's
research, the seller's files and the seller's cloned sections with their current visible text and
slot names. Use web_search (with include_domains set to the seller's domain) and fetch_page to
find and verify the seller's own published case studies, and read_seller_file for a seller file
that is listed but not included.

Your final answer is the complete plan.md, in this shape and nothing else:

# <page title>

## 0. Message plan
(the seven items from the skill's section 1)

## Sections
For each section, in page order:
### <n>. <name> — clone <fragment_id>
- Question: the one question it answers
- Slots: one line per slot to change, `slot_name: new value` (only slot names listed for that
  clone; leave out slots that keep their original value)
- Text edits: one line per visible text with no slot, `"exact current text" -> "new text"`
- Buttons: `label -> https://...` for every button in the section, or `none`
- Keep: what stays exactly as captured (images, icons, logo rows, wording that already fits)
- Words: about how many visible words the section has after your edits

## Shell
- Prepared for: <account name>
- Header button: <label> -> <url>

## Left out of the page
(sections of the seller's site you are not using, and why)

## Final check
(the skill's section 6, one line per item, each marked pass or fixed)

SKILL
=====
"""


def _text_of(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    lines: list[str] = []
    for node in soup.find_all(string=True):
        text = " ".join(node.split())
        if text and not text.startswith("{{wf"):
            lines.append(text)
    deduped: list[str] = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return deduped


def clone_catalog(registry: Any, *, kit_version: int | None) -> str:
    """Every approved original clone of the kit, in page order, as text."""
    listed = registry.list_sections()
    blocks: list[str] = []
    for row in listed.get("sections") or []:
        label = str(row.get("label") or "")
        role = str(row.get("section_role") or "")
        if role in SKIP_ROLES or any(skip in label for skip in SKIP_LABELS):
            continue
        source = registry.read_source(str(row["fragment_id"]))
        page = str(source.get("page_url") or "")
        if source.get("derived_from") or source.get("composed") or page.startswith("composed"):
            continue  # earlier runs' variants and agent-composed sections are not the seller's
        if kit_version is not None and source.get("source_kit_version") not in (None, kit_version):
            continue
        slots = source.get("slots") or []
        slot_names = [
            str(slot.get("key") or slot.get("name") or slot)
            if isinstance(slot, dict)
            else str(slot)
            for slot in slots
        ]
        text = _text_of(source.get("html") or "")
        if len(text) > 40:
            text = text[:40] + [f"... ({len(text) - 40} more text items, mostly repeated quotes)"]
        blocks.append(
            f"### {source['fragment_id']} — {role} — {source.get('page_url') or source.get('source_url')}\n"
            f"slots: {', '.join(slot_names) or 'none'}\n"
            "visible text, in order:\n" + "\n".join(f"- {line}" for line in text)
        )
    return "\n\n".join(blocks)


def research_text(reads: Any, *, account_entity_id: str) -> str:
    parts: list[str] = []
    for section in ("overview", "insights"):
        offset: int | None = 0
        while offset is not None:
            page = reads.read_account_research(
                account_entity_id=account_entity_id, section=section, offset=offset
            )
            parts.append(json.dumps(page.get(section) or page, ensure_ascii=False))
            offset = page.get("next_offset")
    return "\n".join(parts)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def seller_text(knowledge: Any, *, brief: str) -> str:
    """The products the brief names, the proof files and the confirmed ICP in full; every other
    seller file stays available through read_seller_file. (The project's product set is stored
    as ids, so products are matched by the names the brief uses.)"""
    brief_lower = brief.lower()
    product_slugs = {
        Path(doc.path).stem
        for doc in knowledge.documents
        if doc.path.startswith("product/")
        and (doc.path in brief or Path(doc.path).stem.replace("-", " ") in brief_lower)
        and Path(doc.path).stem != "catalog"
    }
    included, listed = [], []
    for doc in knowledge.documents:
        stem = Path(doc.path).stem
        if (
            doc.path.startswith("proof/")
            or doc.path == knowledge.confirmed_icp_path
            or Path(doc.path).name == "index.md"
            or (doc.path.startswith("product/") and stem in product_slugs)
        ):
            included.append(f"### {doc.path} ({doc.kind})\n{doc.body_text}")
        else:
            listed.append(f"- {doc.path} ({doc.kind}, {len(doc.body_text)} characters)")
    return (
        "\n\n".join(included)
        + "\n\n### Other seller files (open with read_seller_file)\n"
        + "\n".join(listed)
    )


def fetch_page_text(url: str) -> str:
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/140.0"},
    )
    text = "\n".join(_text_of(response.text))
    return f"status {response.status_code}, url {response.url}\n{text[:FETCH_LIMIT]}"


def run_copy_stage(
    *,
    config: Any,
    reads: Any,
    registry: Any,
    brief: str,
    account_entity_id: str,
    kit_version: int | None,
    skill_text: str,
    out: Path,
) -> str:
    from langchain.agents import create_agent
    from langchain_core.tools import tool
    from lumen_agent.llm import init_model

    @tool
    def web_search(
        query: str, include_domains: list[str] | None = None, num_results: int = 8
    ) -> str:
        """Search the web. Set include_domains to the seller's domain to find its own published
        case studies, customer stories and studies. Returns titles, URLs and passages."""
        result = reads.web_search(
            query=query, num_results=num_results, include_domains=include_domains
        )
        return json.dumps(result, ensure_ascii=False)[:FETCH_LIMIT]

    knowledge = reads.seller_knowledge()
    documents = {doc.path: doc.body_text for doc in knowledge.documents}

    @tool
    def read_seller_file(path: str) -> str:
        """Read one of the seller's files by its path, for example company/overview.md."""
        return documents.get(
            path.lstrip("/"), f"no seller file at {path}; known: {sorted(documents)}"
        )

    @tool
    def fetch_page(url: str) -> str:
        """Open one page and return its visible text. Use it before you use any number or quote
        from a case study."""
        try:
            return fetch_page_text(url)
        except Exception as error:  # a failed fetch is an answer the model can act on
            return f"fetch failed: {error}"

    inputs = (
        f"# Brief\n{brief}\n\n"
        f"# Account research (overview and insights)\n"
        f"{research_text(reads, account_entity_id=account_entity_id)}\n\n"
        f"# Seller files\n{seller_text(knowledge, brief=brief)}\n\n"
        f"# Seller's cloned sections\n{clone_catalog(registry, kit_version=kit_version)}\n"
    )
    (out / "copy-stage-input.md").write_text(inputs)

    model = init_model(
        config.orchestrator_model,
        base_url=config.agent_base_url,
        api_key=config.agent_api_key,
        reasoning=config.agent_reasoning,
        provider_sort=config.agent_provider_sort,
        role="copy_stage",
        chat_completions=config.agent_chat_completions,
    )
    agent = create_agent(
        model, tools=[web_search, fetch_page, read_seller_file], system_prompt=SYSTEM + skill_text
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": inputs}]}, {"recursion_limit": 30}
    )
    messages = result["messages"]
    usage = [
        getattr(message, "usage_metadata", None)
        for message in messages
        if getattr(message, "usage_metadata", None)
    ]
    (out / "copy-stage-usage.json").write_text(json.dumps(usage, indent=2, default=str))
    transcript = [
        {
            "type": message.type,
            "content": message.content
            if isinstance(message.content, str)
            else str(message.content),
            "tool_calls": getattr(message, "tool_calls", None),
        }
        for message in messages
    ]
    (out / "copy-stage-transcript.json").write_text(json.dumps(transcript, indent=2, default=str))
    final = messages[-1].content
    plan = final if isinstance(final, str) else str(final)
    plan = re.sub(r"^```(?:markdown)?\n|\n```$", "", plan.strip())
    (out / "copy-stage-plan.md").write_text(plan)
    return plan
