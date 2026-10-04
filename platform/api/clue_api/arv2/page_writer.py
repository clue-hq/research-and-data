"""The separate page writer: one plain model call per page set, checked for correctness only.

The research agent records findings; this module turns them into the account's Overview and
Insights or a person's contact page. Inputs come from :mod:`page_writer_view` (durable rows only).
The model returns JSON; deterministic checks verify what can be verified — references resolve,
quotations appear in a cited finding, owned sections are present, private topics are absent,
send lines only in contact openers — and one repair call is allowed. Code never counts or trims
prose: length and shape are the guides' business (founder ruling 2026-10-04).

The model is injected (:data:`ModelCall`), so production routes it through the platform gateway
and the trial harness through its own client, with identical prompts and checks.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from clue_api.arv2.display.recipes import Page
from clue_api.arv2.page_writer_view import (
    Person,
    account_view,
    claim_ids,
    contact_view,
    finding_texts,
)
from clue_api.arv2.quality_pages import CitedItem, CitedSentence, PageSectionDraft

#: Messages in, raw model text out. ``json_mode`` asks for a JSON object.
ModelCall = Callable[[Sequence[Mapping[str, str]], bool], Awaitable[str]]

GUIDES = Path(__file__).resolve().parents[3] / "agents/catalog/research-quality/skills"
GUIDE_VERSION = "v1"

SECTIONS: dict[str, tuple[str, ...]] = {
    "overview": (
        "what-they-do",
        "why-they-fit",
        "why-now",
        "buying-committee",
        "how-to-approach",
        "watch-outs",
    ),
    "insights": (
        "buying-signals",
        "money-and-momentum",
        "tools-they-already-use",
        "how-they-sell",
        "miscellaneous",
    ),
    "contact": (
        "why-this-person",
        "problem-right-now",
        "openers",
        "angles",
        "do-not-mention",
        "miscellaneous",
    ),
}

OUTPUT_SHAPE = """Return one JSON object, no prose around it:
{"pages": [{"page": "<page>", "sections": [{"key": "<section key>",
  "intro": [Sentence...], "items": [{"h2": "<heading>", "body": [Sentence...],
  "contact_ids": ["<uuid>"...], "send_line": Sentence or null}], "gaps": ["<text>"...]}]}]}
Sentence = {"text": "...", "kind": "fact|quote|inference|gap", "refs": ["F012", ...]}
Write every listed section exactly once, in the listed order. Use contact_ids only from the
committee list. send_line is only for openers."""

#: Private matters never appear on a page (shared guide, rule 8). What a company offers its staff
#: (an employee assistance programme, say) is not a private matter, so the patterns are personal.
PRIVATE = re.compile(
    r"antidepress|\btherapist\b|\b(?:his|her|their) (?:therapy|medication|diagnosis)\b"
    r"|mental[- ]health (?:post|disclosure|safety moment)|campaign[- ]finance|\bsecurities\b"
    r"|\b(?:share|stock) holdings\b|income source|\bdisciplinary (?:record|order|action)\b"
    r"|board of accountancy|\bcensure\b|obituar|\bhome (?:town|state|address)\b"
    r"|where (?:she|he|they) live",
    re.I,
)

_QUOTE = re.compile(r'[“"]([^”"]{12,})[”"]')
_KINDS = {"fact", "quote", "inference", "gap", "qualified"}


class PageWriterError(ValueError):
    """The writer could not produce a page that passes the correctness checks."""


def guide(name: str) -> str:
    text = (GUIDES / name / GUIDE_VERSION / "SKILL.md").read_text(encoding="utf-8")
    return text.split("---", 2)[2].strip() if text.startswith("---") else text


def account_system() -> str:
    return guide("research-page-writing") + "\n\n" + guide("account-pages")


def contact_system() -> str:
    return guide("research-page-writing") + "\n\n" + guide("contact-page")


def seller_brief_system() -> str:
    return guide("seller-brief")


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-")):
        value = value.replace(a, b)
    return re.sub(r"\s+", " ", value).lower()


def _sentences(section: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    for s in section.get("intro") or []:
        if isinstance(s, Mapping):
            yield "intro", s
    for item in section.get("items") or []:
        for s in item.get("body") or []:
            if isinstance(s, Mapping):
                yield "body", s
        if isinstance(item.get("send_line"), Mapping):
            yield "send_line", item["send_line"]


def check_pages(
    result: Mapping[str, Any],
    pages: Sequence[str],
    texts: Mapping[str, str],
    contacts: set[str],
) -> list[str]:
    """Correctness problems in a writer result; empty when it can be published."""
    errors: list[str] = []
    got = {p.get("page"): p for p in result.get("pages") or [] if isinstance(p, Mapping)}
    if set(got) != set(pages):
        return [f"pages {sorted(map(str, got))} != {sorted(pages)}"]
    for page in pages:
        sections = [s for s in got[page].get("sections") or [] if isinstance(s, Mapping)]
        keys = [s.get("key") for s in sections]
        if tuple(keys) != SECTIONS[page]:
            errors.append(f"{page}: sections {keys} != {list(SECTIONS[page])}")
        for section in sections:
            where = f"{page}/{section.get('key')}"
            for item in section.get("items") or []:
                if not str(item.get("h2") or "").strip():
                    errors.append(f"{where}: an item has no heading")
                if not item.get("body"):
                    errors.append(f"{where}: item '{item.get('h2')}' has no body")
                for cid in item.get("contact_ids") or []:
                    if cid not in contacts:
                        errors.append(f"{where}: unknown contact {cid}")
                if item.get("send_line") and (page, section.get("key")) != ("contact", "openers"):
                    errors.append(f"{where}: send_line outside contact openers")
                if PRIVATE.search(str(item.get("h2") or "")):
                    errors.append(f"{where}: heading mentions a private matter")
            for slot, s in _sentences(section):
                text = str(s.get("text") or "")
                refs = list(s.get("refs") or [])
                if not text.strip():
                    errors.append(f"{where}: a sentence has no text")
                    continue
                if s.get("kind", "fact") not in _KINDS:
                    errors.append(f"{where}: unknown sentence kind {s.get('kind')}")
                if unknown := [r for r in refs if r not in texts]:
                    errors.append(f"{where}: unknown refs {unknown}")
                if s.get("kind") in ("fact", "quote") and not refs and slot != "send_line":
                    errors.append(f"{where}: uncited {s.get('kind')}: {text[:80]}")
                if PRIVATE.search(text):
                    errors.append(f"{where}: mentions a private matter: {text[:80]}")
                if slot == "send_line":
                    continue
                cited = _norm(" ".join(texts.get(r, "") for r in refs))
                for quote in _QUOTE.findall(text):
                    parts = [p for p in re.split(r"\.\.\.|…", quote) if len(p.strip()) >= 10]
                    if not all(_norm(p).strip(" .,;:") in cited for p in parts):
                        errors.append(f"{where}: quote not in cited findings: “{quote[:90]}”")
    return errors


def parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("the writer returned JSON that is not an object")
    return value


@dataclass(frozen=True)
class WriterResult:
    result: dict[str, Any]
    attempts: int


async def write_checked(
    model: ModelCall,
    system: str,
    user: str,
    check: Callable[[Mapping[str, Any]], list[str]],
) -> WriterResult:
    """One write and at most one repair. Raises :class:`PageWriterError` if both fail."""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = await model(messages, True)
    try:
        result = parse_json(raw)
        errors = check(result)
    except (json.JSONDecodeError, ValueError, AttributeError, TypeError) as exc:
        result, errors = {}, [f"output is not valid JSON of the requested shape: {exc}"]
    if not errors:
        return WriterResult(result, 1)
    repair = (
        "Your page failed these checks:\n- "
        + "\n- ".join(errors[:40])
        + "\n\nReturn the corrected complete JSON object. Keep everything that passed;"
        " fix only what failed."
    )
    raw2 = await model(
        [*messages, {"role": "assistant", "content": raw}, {"role": "user", "content": repair}],
        True,
    )
    try:
        result2 = parse_json(raw2)
        errors2 = check(result2)
    except (json.JSONDecodeError, ValueError, AttributeError, TypeError) as exc:
        errors2 = [f"repair output is not valid JSON of the requested shape: {exc}"]
        result2 = {}
    if errors2:
        raise PageWriterError("; ".join(errors2[:10]))
    return WriterResult(result2, 2)


def _sentence(s: Mapping[str, Any], claims: Mapping[str, UUID]) -> CitedSentence:
    return CitedSentence(
        text=str(s["text"]).strip(),
        claim_ids=tuple(dict.fromkeys(claims[r] for r in s.get("refs") or [] if r in claims)),
        kind=s.get("kind", "fact"),
    )


def to_drafts(
    result: Mapping[str, Any], claims: Mapping[str, UUID]
) -> dict[Page, tuple[PageSectionDraft, ...]]:
    """Checked writer output as the existing typed page drafts, references resolved to claims."""
    drafts: dict[Page, tuple[PageSectionDraft, ...]] = {}
    for page in result["pages"]:
        sections = []
        for section in page["sections"]:
            sections.append(
                PageSectionDraft(
                    key=section["key"],
                    intro=tuple(_sentence(s, claims) for s in section.get("intro") or []),
                    items=tuple(
                        CitedItem(
                            h2=str(item["h2"]).strip(),
                            body=tuple(_sentence(s, claims) for s in item["body"]),
                            contact_ids=tuple(UUID(c) for c in item.get("contact_ids") or []),
                            send_line=_sentence(item["send_line"], claims)
                            if item.get("send_line")
                            else None,
                        )
                        for item in section.get("items") or []
                    ),
                    gaps=tuple(str(g) for g in section.get("gaps") or []),
                )
            )
        drafts[cast(Page, page["page"])] = tuple(sections)
    return drafts


def _request(view: str, pages: Sequence[str]) -> str:
    lines = "\n".join(f"{page}: {', '.join(SECTIONS[page])}" for page in pages)
    heading = "these pages" if len(pages) > 1 else "this page"
    return f"{view}\n\n# Write {heading}\n\n{lines}\n\n{OUTPUT_SHAPE}"


@dataclass(frozen=True)
class WrittenPages:
    drafts: dict[Page, tuple[PageSectionDraft, ...]]
    result: dict[str, Any]
    attempts: int

    @property
    def story(self) -> str:
        """The account's short version (why-they-fit intro), for its contact pages."""
        for page in self.result.get("pages") or []:
            for section in page.get("sections") or []:
                if page.get("page") == "overview" and section.get("key") == "why-they-fit":
                    return " ".join(str(s.get("text") or "") for s in section.get("intro") or [])
        return ""


async def write_account_pages(
    model: ModelCall,
    *,
    seller_brief: str,
    account_name: str,
    account_dossier: Mapping[str, Any],
    people: Sequence[Person],
) -> WrittenPages:
    texts = finding_texts(account_dossier)
    claims = claim_ids(account_dossier)
    for number, person in enumerate(people, start=1):
        texts.update(finding_texts(person.dossier, prefix=f"P{number}:"))
        claims.update(claim_ids(person.dossier, prefix=f"P{number}:"))
    contacts = {str(p.contact_id) for p in people}
    pages = ("overview", "insights")
    user = _request(
        account_view(
            seller_brief=seller_brief,
            account_name=account_name,
            account_dossier=account_dossier,
            people=people,
        ),
        pages,
    )
    written = await write_checked(
        model, account_system(), user, lambda r: check_pages(r, pages, texts, contacts)
    )
    return WrittenPages(to_drafts(written.result, claims), written.result, written.attempts)


async def write_contact_page(
    model: ModelCall,
    *,
    seller_brief: str,
    account_name: str,
    account_story: str,
    person: Person,
    account_dossier: Mapping[str, Any],
) -> WrittenPages:
    texts = finding_texts(person.dossier) | finding_texts(account_dossier, prefix="A:")
    claims = claim_ids(person.dossier) | claim_ids(account_dossier, prefix="A:")
    pages = ("contact",)
    user = _request(
        contact_view(
            seller_brief=seller_brief,
            account_name=account_name,
            account_story=account_story,
            person=person,
            account_dossier=account_dossier,
        ),
        pages,
    )
    written = await write_checked(
        model, contact_system(), user, lambda r: check_pages(r, pages, texts, set())
    )
    return WrittenPages(to_drafts(written.result, claims), written.result, written.attempts)


def seller_brief_request(
    *,
    seller_name: str,
    products: Mapping[str, str],
    gaps: Sequence[str],
    documents: Sequence[tuple[str, str, str]],
) -> str:
    """The seller-brief request: pinned seller documents as (kind, path, body)."""
    docs = "\n\n".join(f"## Document: {kind} ({path})\n\n{body}" for kind, path, body in documents)
    return (
        f"Seller: {seller_name}\nSelected products: {json.dumps(dict(products))}\n"
        f"Context gaps: {list(gaps)}\n\n{docs}"
    )
