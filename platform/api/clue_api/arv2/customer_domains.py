"""Does each customer domain Exa gave really belong to that customer? (spec 2026-10-16-discovery-
excludes-seller-customers §4.2.)

One GET of each distinct domain's homepage. A page that names the company is ``confirmed``; a page
about something else is ``unconfirmed``; a homepage that did not answer (blocked, refused, down) is
``unchecked``, because silence says nothing about the domain. Nothing is ever dropped: the label
only informs the Head of ABM, who decides what to exclude. The page title is kept for every answered
page, confirmed ones too, because a name check cannot tell two companies with one name apart: the
2026-10-16 live run confirmed ``wynwoodhouse.us``, a Pennsylvania care home also called Wynwood
House, for the Latin American hospitality group of that name.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Literal

from clue_api.arv2.calls import CallSpec, ProviderCaller
from clue_api.arv2.media_resolution import PUBLIC_HEADERS, public_url
from clue_api.arv2.transport import HttpRequest

__all__ = ["DomainCheck", "check_domains", "names_company"]

#: Words a company name carries that a homepage need not repeat.
_NAME_NOISE = frozenset(
    {"the", "inc", "ltd", "llc", "co", "corp", "corporation", "company", "group", "limited",
     "gmbh", "plc", "holdings", "sa", "ag", "pty"}
)  # fmt: skip
#: How much of the visible text, after the title, a name may appear in.
_TEXT_WINDOW = 5000


@dataclass(frozen=True)
class DomainCheck:
    status: Literal["confirmed", "unconfirmed", "unchecked"]
    title: str | None


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: list[str] = []
        self.text: list[str] = []
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title.append(data)
        elif not self._skip and data.strip():
            self.text.append(data.strip())


def _words(value: str) -> list[str]:
    return [_singular(word) for word in re.sub(r"[^a-z0-9]+", " ", value.lower()).split()]


def _singular(word: str) -> str:
    """ "rentals" and "rental" are one word to a name check."""
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def names_company(name: str, page: str) -> bool:
    """True when every significant word of ``name`` is a whole word on ``page``, or a name of two or
    more words is one whole word there run together ("Host Genius" on a "HostGenius" page). Never a
    match inside a longer word ("Sage" in "message"), and a name with no significant word never
    matches: the check errs towards ``unconfirmed``."""
    wanted = [word for word in _words(name) if word not in _NAME_NOISE]
    if not wanted:
        return False
    words = _words(page)
    on_page = set(words)
    if set(wanted) <= on_page:
        return True
    joined = "".join(wanted)
    if len(wanted) > 1 and joined in on_page:
        return True
    # "BlueGems" on a "Blue Gems" page: the name run together is two page words run together.
    return joined in {first + second for first, second in zip(words, words[1:], strict=False)}


def _named_domain(domain: str, name: str, page: str) -> bool:
    """A domain spelled as the company's name ("cur8.earth" for "Cur8 Earth Limited") whose page
    shows that name as a whole word."""
    label = _words(domain.split(".")[0])
    wanted = [word for word in _words(name) if word not in _NAME_NOISE]
    return len(label) == 1 and label[0] in wanted and label[0] in set(_words(page))


def _homepage(caller: ProviderCaller, domain: str) -> tuple[bool, str | None, str]:
    """``(answered, title, page text)``; any failure is an unanswered page."""
    try:
        url = public_url(f"https://{domain}/")
        result = caller.call(
            CallSpec(
                provider="public_media",
                operation="GET",
                label="onboarding.customer_domain",
                request=HttpRequest(method="GET", url=url, headers=PUBLIC_HEADERS, timeout_s=20),
                max_attempts=1,
                keep_body=False,
            )
        )
    except Exception:
        return False, None, ""
    response = result.response
    if not 200 <= response.status < 300:
        return False, None, ""
    page = _Page()
    page.feed(response.body.decode("utf-8", errors="replace"))
    title = " ".join(" ".join(page.title).split()) or None
    return True, title, f"{title or ''} {' '.join(page.text)[:_TEXT_WINDOW]}"


def check_domains(
    caller: ProviderCaller, customers: Sequence[Mapping[str, Any]]
) -> dict[str, DomainCheck]:
    """Label every distinct domain of ``customers`` (keyed as written). A domain two customers
    share is fetched once and confirmed when its page names either of them."""
    names: dict[str, list[str]] = {}
    for customer in customers:
        for domain in customer.get("domains") or []:
            if isinstance(domain, str) and domain.strip():
                names.setdefault(domain.strip(), []).append(str(customer.get("name") or ""))
    checks: dict[str, DomainCheck] = {}
    for domain, owners in names.items():
        answered, title, text = _homepage(caller, domain)
        if not answered:
            checks[domain] = DomainCheck("unchecked", None)
            continue
        confirmed = any(
            names_company(owner, text) or _named_domain(domain, owner, text) for owner in owners
        )
        checks[domain] = DomainCheck("confirmed" if confirmed else "unconfirmed", title)
    return checks
