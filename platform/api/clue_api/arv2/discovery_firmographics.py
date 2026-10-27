"""Firmographics for discovered accounts, from AI Ark, the moment discovery finds them.

Founder ruling 2026-10-27: the target-accounts table's company facts (industry, revenue,
headcount, location, LinkedIn, Twitter) need no deep research. Discovery enriches every account it
accepts with one AI Ark search per round, and deep research no longer re-saves a field discovery
already filled from AI Ark (``committee_discovery.company_lock``).

**Choosing the record (the strict rule).** AI Ark files every company page under the domain it
lists, so a group shares its domain with each of its hotels or schools: ``wandahotels.com`` holds
52 records, and the group's own page is not the biggest. The trial on 135 real accounts settled
the rule the founder approved:

1. Only records of the account's own domain are considered: filed there by AI Ark, or whose own
   website is there.
2. With several records, stray pages under five staff are set aside ("Toro Inc", "Toro Asia").
3. The record's name must match the account's name once case, accents, punctuation, "&"/"and"
   and company suffixes are set aside — exactly, never "close enough". A single record must match
   too: ``mitsubishicarbide.com``'s only record is a UK subsidiary.
4. Identical names are duplicate pages of one company: the one whose own website is the domain's
   homepage wins, then the larger one.

Anything else resolves to nothing, and the account keeps empty fields for deep research to fill:
an empty field is honest, a wrong company's facts would not be.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Final, Literal
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import ai_ark_company_claims
from clue_api.arv2.ai_ark_client import AiArkCompany
from clue_api.arv2.claim_writer import ClaimDraft
from clue_api.arv2.structuring_client import FieldCatalog
from clue_core import EntityId, ResearchMode

#: The claims the target-accounts table reads for these columns (``frontend_read/accounts_list``):
#: industry (and the list), revenue band, headcount (count and range), HQ, LinkedIn and Twitter.
FIRMOGRAPHIC_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "core.industry",
        "core.industries_all",
        "core.revenue_band",
        "core.annual_revenue",
        "core.employee_count",
        "core.employee_range",
        "core.hq_location",
        "core.company_linkedin_url",
        "core.company_twitter_url",
    }
)

#: AI Ark company claims carry this source key wherever they are written.
AI_ARK_COMPANY_SOURCE: Final = "ai_ark:company"

#: Below this many staff, a record among several is a stray or placeholder page.
MIN_STAFF_AMONG_SEVERAL: Final = 5

#: Words that name a company's legal form, not the company.
_SUFFIXES: Final = frozenset(
    {
        "inc",
        "llc",
        "ltd",
        "limited",
        "co",
        "corp",
        "corporation",
        "company",
        "plc",
        "sa",
        "gmbh",
        "the",
        "and",
    }
)

How = Literal["single_record", "exact_name", "exact_name_tiebreak"]


@dataclass(frozen=True)
class Resolution:
    """The record a discovered account is, and how it was chosen (stamped on every claim)."""

    company: AiArkCompany
    how: How


def _name_tokens(name: str | None) -> tuple[str, ...]:
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    folded = re.sub(r"[^a-z0-9 ]+", " ", folded.replace("&", " and ").replace("+", " and "))
    return tuple(token for token in folded.split() if token not in _SUFFIXES)


def names_match(a: str | None, b: str | None) -> bool:
    """Whether two company names are the same name once form and spelling are set aside."""
    left = _name_tokens(a)
    return bool(left) and left == _name_tokens(b)


def fold_domain(value: str | None) -> str:
    """A domain as compared: lower-case, no scheme, no ``www.``, no path (AI Ark sometimes files
    a domain as a full URL, ``http://www.hmalpha.com``)."""
    rest = re.sub(r"^https?://", "", (value or "").strip().lower())
    return rest.partition("/")[0].removeprefix("www.")


def _website(company: AiArkCompany) -> tuple[str, str]:
    """The record's own website as (host, path), lower-cased, ``www.`` and slashes dropped."""
    link = company.raw.get("link") if isinstance(company.raw, dict) else None
    website = link.get("website") if isinstance(link, dict) else None
    if not isinstance(website, str):
        return "", ""
    rest = re.sub(r"^https?://", "", website.strip().lower())
    host, _, path = rest.partition("/")
    return host.removeprefix("www."), path.strip("/")


def _website_is_homepage(company: AiArkCompany, domain: str) -> bool:
    return _website(company) == (domain, "")


def _on_domain(company: AiArkCompany, domain: str) -> bool:
    """Whether a record is about ``domain``: AI Ark files it there, or its own website is there.

    Live run 2026-10-27: AI Ark files eHealth, Inc. under ``ehealthinsurance.com`` while its own
    website is ``eHealth.com``, the domain discovery found it by.
    """
    return fold_domain(company.domain) == domain or _website(company)[0] == domain


def resolve_company(
    domain: str, account_name: str, records: Iterable[AiArkCompany]
) -> Resolution | None:
    """The one record ``account_name`` at ``domain`` is, by the strict rule; else ``None``."""
    domain = fold_domain(domain)
    own = [record for record in records if _on_domain(record, domain)]
    if not own:
        return None
    if len(own) == 1:
        return (
            Resolution(own[0], "single_record") if names_match(own[0].name, account_name) else None
        )
    sized = [r for r in own if (r.employee_count or 0) >= MIN_STAFF_AMONG_SEVERAL]
    named = [r for r in sized if names_match(r.name, account_name)]
    if not named:
        return None
    named.sort(key=lambda r: (_website_is_homepage(r, domain), r.employee_count or 0), reverse=True)
    return Resolution(named[0], "exact_name" if len(named) == 1 else "exact_name_tiebreak")


@dataclass(frozen=True)
class _DiscoveryScope:
    """What the AI Ark claim mapper stamps: this run, this workspace, this account."""

    workspace_id: str
    run_id: UUID
    account_id: EntityId
    account_domain: str

    @property
    def person_subject_id(self) -> EntityId | None:
        return None


def firmographic_drafts(
    resolution: Resolution,
    *,
    workspace_id: str,
    discovery_run_id: UUID,
    account_id: EntityId,
    domain: str,
    catalog: FieldCatalog,
) -> list[ClaimDraft]:
    """The table's company facts from the chosen record, as discovery claims of this run.

    The same mapping deep research uses (``ai_ark_company_claims``), cut down to
    :data:`FIRMOGRAPHIC_FIELDS` and stamped as discovery, with how the record was chosen.
    """
    scope = _DiscoveryScope(workspace_id, discovery_run_id, account_id, domain)
    markers: dict[str, JsonValue] = {
        "discovery_run_id": str(discovery_run_id),
        "resolved_by": resolution.how,
        "ai_ark_company_id": resolution.company.ark_id,
    }
    return [
        replace(
            draft,
            research_mode=ResearchMode.ACCOUNT_DISCOVERY,
            markers={**draft.markers, **markers},
        )
        for draft in ai_ark_company_claims(resolution.company, scope, catalog=catalog)
        if draft.field_key in FIRMOGRAPHIC_FIELDS
    ]


async def ai_ark_firmographics_on_file(
    conn: AsyncConnection, *, workspace_id: str, account_id: EntityId
) -> frozenset[str]:
    """The firmographic fields this account already has a live AI Ark value for."""
    rows = await conn.execute(
        text(
            "SELECT DISTINCT field_key FROM claim "
            "WHERE workspace_id = :ws AND entity_id = :entity AND source_key = :source "
            "AND superseded_by IS NULL AND field_key IN :fields"
        ).bindparams(bindparam("fields", expanding=True)),
        {
            "ws": workspace_id,
            "entity": UUID(str(account_id)),
            "source": AI_ARK_COMPANY_SOURCE,
            "fields": sorted(FIRMOGRAPHIC_FIELDS),
        },
    )
    return frozenset(str(row[0]) for row in rows)


def without_fields(drafts: Sequence[ClaimDraft], fields: frozenset[str]) -> list[ClaimDraft]:
    """``drafts`` minus any claim for one of ``fields``."""
    return [draft for draft in drafts if draft.field_key not in fields]
