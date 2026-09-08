"""The shared contract-v1 rules — one home for every display decision the five endpoints make.

``contract_v1`` says what a payload's fields *are*; this module decides what goes **in** them. The
split matters because the same rule is asked for on several screens: the accounts list, the account
detail and the contact page all need the fit band, the same custom fields, the same relative
activity labels. A copy per endpoint is how three screens end up disagreeing about one account.

Four rules shape everything here.

1. **The display predicate is a lane decision, not the C7 one.**
   :func:`arv2_display_allowed` deliberately does *not* consult ``identity_binding`` (D3 ruling
   S10). C7's :func:`~clue_api.research_view_governance.display_allowed` refuses a contact claim
   whose binding is not ``STRONG``; on the ARV2 lane the binding is a research-quality signal that
   the lenient writer stamps ``WEAK`` by default, so honouring it would blank the contacts screens
   for facts the workspace policy plainly permits. The two predicates therefore live side by side
   on purpose, each named for the surface it governs.
2. **A label is served, never derived in the browser.** Tenure, "3 hours ago", "400 (201-500)" —
   all of them are computed here against an explicitly passed ``now``, so a test can pin them and
   the frontend can never disagree with the backend about what time it is.
3. **An unknown is ``"Unknown"`` or absent, never invented.** Where the Zod schema requires a
   non-empty string, :data:`EMPTY_BAND` is the documented placeholder; where it permits ``None``,
   ``None`` is the honest answer. No band is guessed from a missing score.
4. **Every claim read is entity-scoped and workspace-scoped.** The claim reads here go through
   ``WorkspaceScope.for_workspace(...).predicate()`` on top of an entity-id filter — never
   ``claim.workspace_id`` alone, which would serve another tenant's public-footprint rows.

This module may import ``clue_api.arv2.display.*`` (the D2 lane's render/evidence helpers); the
reverse import stays forbidden.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.evidence import evidence_for_ids
from clue_api.arv2.display.render import render_value_text
from clue_api.frontend_read.contract_v1 import (
    AccountActivity,
    AccountCustomField,
    AccountFit,
    AccountOwner,
    AccountSocial,
    ClueActor,
    PersonActor,
    ResearchEvidence,
    ResearchStatus,
)
from clue_api.research_view_governance import safe_public_url
from clue_config import Settings
from clue_core import Claim, EntityId, EntityType, UseClass, decode_jsonb_scalar
from clue_research.claimstore import WorkspaceScope
from clue_research.compliance import WorkspacePolicy

__all__ = [
    "EMPTY_BAND",
    "INFLUENCE_DEFAULTS",
    "PERSONA_RANK",
    "PERSONA_TONES",
    "PROVIDER_LABELS",
    "RESEARCH_STATUS_LABELS",
    "EmailFacts",
    "activity_for",
    "arv2_display_allowed",
    "arv2_research_status_for",
    "band_for_headcount",
    "contact_last_modified",
    "current_position_start",
    "custom_fields_for",
    "education_label",
    "email_facts",
    "employee_band",
    "employee_range_label",
    "fit_band",
    "fit_score_100",
    "funding_label",
    "headcount_label",
    "industry_labels",
    "iso_utc",
    "location_label",
    "last_modified_for",
    "linkedin_label",
    "owners_for",
    "research_evidence_for",
    "revenue_label",
    "socials",
    "tenure",
    "time_label",
    "website_label",
    "website_url",
]

PersonaTone = Literal["olive", "orange", "blue", "cyan", "green", "pink", "red"]
Influence = Literal["High", "Medium", "Low"]
Presentation = Literal["text", "badge", "score"]


# --- the display predicate ------------------------------------------------------------------------


def arv2_display_allowed(claim: Claim, policy: WorkspacePolicy) -> bool:
    """Whether ``claim`` may appear on an ARV2 accounts screen under ``policy``.

    The order is the ruling's order and each step is a decision:

    * an **account** claim is always displayable — governance here is personal-data governance, and
      an account fact has no data subject;
    * a ``sensitive`` claim follows ``display_sensitive`` and nothing else (it is fail-closed, and
      the sensitivity floor has usually already marked it outreach-unsafe, so testing safety first
      would make the switch unreachable);
    * an **outreach-unsafe** contact claim is refused here. It is not forbidden everywhere — it may
      appear inside a ``restricted`` section ("do-not-mention" / "context-only" / "watch-outs"),
      and the display module routes those itself rather than asking this predicate;
    * the remaining use-classes read their own workspace switch.

    A contact claim whose ``use_class`` is ``None`` is treated as ``professional-public``. The
    lenient writer only leaves it ``None`` on **non-facet** contact fields —
    ``contact.current_title`` and its neighbours, which it never defaults — so refusing them would
    blank every title, company and location on the contacts screens, for a field class that is
    professional by construction.

    ``identity_binding`` is **never** consulted (ruling S10); see the module docstring.
    """

    if claim.entity_type is EntityType.ACCOUNT:
        return True
    if claim.use_class is UseClass.SENSITIVE:
        return policy.display_sensitive
    if claim.outreach_safe is False:
        return False
    if claim.use_class is UseClass.PERSONAL_PUBLIC_NON_SENSITIVE:
        return policy.display_personal_public_non_sensitive
    return policy.display_professional_public


# --- the label maps -------------------------------------------------------------------------------

#: The five research states the backend distinguishes, in the words the screen shows. ``completed``
#: reads "Researched" rather than "Completed": the noun the marketer cares about is the research.
RESEARCH_STATUS_LABELS: dict[ResearchStatus, str] = {
    "not_started": "Not started",
    "in_progress": "In progress",
    "needs_review": "Needs review",
    "completed": "Researched",
    "suspended": "Paused",
}

#: The chip colour per persona. An unrecognised persona takes ``"green"`` — the neutral tone — so a
#: vocabulary the committee adds later renders plainly instead of failing the payload's Literal.
PERSONA_TONES: dict[str, PersonaTone] = {
    "economic_buyer": "olive",
    "champion": "orange",
    "technical_evaluator": "blue",
    "user": "cyan",
    "blocker": "red",
}

#: The influence a persona implies when the committee claim does not carry one (ruling S8).
INFLUENCE_DEFAULTS: dict[str, Influence] = {
    "economic_buyer": "High",
    "champion": "High",
    "technical_evaluator": "Medium",
    "user": "Medium",
    "blocker": "Medium",
}

#: Committee ordering. A persona outside this tuple sorts last, then by name.
PERSONA_RANK: tuple[str, ...] = (
    "economic_buyer",
    "champion",
    "technical_evaluator",
    "user",
    "blocker",
)

#: ``source_key`` → the provider name a person recognises. An unmapped key is served verbatim: a
#: source we have not named yet is still an honest attribution.
PROVIDER_LABELS: dict[str, str] = {
    "ai_ark": "AI Ark",
    "exa_contents": "Exa",
    "exa_search": "Exa",
    "exa_deep": "Exa",
    "ashby_posting_api": "Ashby",
    "gemini": "Gemini transcript",
    "client_interview": "Interview",
    "client_interview_judged": "Interview",
}

#: What a required band/label string says when nothing is known (decision 16).
EMPTY_BAND = "Unknown"

#: The neutral persona tone.
_DEFAULT_TONE: PersonaTone = "green"

#: The neutral influence.
_DEFAULT_INFLUENCE: Influence = "Medium"


def persona_tone(persona: str | None) -> PersonaTone:
    """The chip tone for ``persona``; the neutral tone for one we do not have a colour for."""
    return PERSONA_TONES.get(persona or "", _DEFAULT_TONE)


def persona_influence(persona: str | None) -> Influence:
    """The persona-derived influence default (ruling S8)."""
    return INFLUENCE_DEFAULTS.get(persona or "", _DEFAULT_INFLUENCE)


def persona_rank(persona: str | None) -> int:
    """Sort key for committee ordering; an unknown persona sorts after every known one."""
    try:
        return PERSONA_RANK.index(persona or "")
    except ValueError:
        return len(PERSONA_RANK)


# --- fit ------------------------------------------------------------------------------------------


def fit_band(score: float | None, *, settings: Settings) -> AccountFit | None:
    """The band for a 0–1 fit score, read from the two configured thresholds (ruling S3).

    ``None`` in, ``None`` out: an unscored account has no band, and "Medium" would be a fabrication.
    """
    if score is None:
        return None
    if score >= settings.arv2_fit_high_threshold:
        return "High"
    if score >= settings.arv2_fit_medium_threshold:
        return "Medium"
    return "Low"


def fit_score_100(score: float | None) -> int | None:
    """A 0–1 fit score as the 0–100 integer the screens show. Clamped, never wrapped."""
    if score is None:
        return None
    return max(0, min(100, round(100 * score)))


# --- account rail labels --------------------------------------------------------------------------

#: The employee bands, as ``(upper_bound_inclusive, label)`` walked in order. The last entry is the
#: open-ended top band and its bound is only a sentinel.
_HEADCOUNT_BANDS: tuple[tuple[int, str], ...] = (
    (10, "1-10"),
    (50, "11-50"),
    (200, "51-200"),
    (500, "201-500"),
    (1000, "501-1000"),
    (5000, "1001-5000"),
    (10000, "5001-10000"),
)

_TOP_HEADCOUNT_BAND = "10001+"


def band_for_headcount(n: int | None) -> str | None:
    """The employee band a headcount falls in, or ``None`` when there is no usable count.

    A count below 1 is not a small company, it is a bad row: it yields ``None`` so the caller falls
    back to :data:`EMPTY_BAND` rather than claiming "1-10".
    """
    if n is None or n < 1:
        return None
    for bound, label in _HEADCOUNT_BANDS:
        if n <= bound:
            return label
    return _TOP_HEADCOUNT_BAND


def _text(value: object) -> str | None:
    """``value`` as a non-empty stripped string, or ``None``."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def employee_range_label(range_json: object) -> str | None:
    """The provider's own employee-range label — ``core.employee_range`` is an object whose only
    required key is ``label`` (``{"label": "101-250", "min": 101, "max": 250}``), and rendering the
    whole object would put ``"label: 101-250; max: 250; min: 101"`` on a table cell. A plain string
    is accepted too: the D1 lenient writer does not enforce the registry's value schema."""
    if isinstance(range_json, dict):
        return _text(range_json.get("label"))
    return _text(range_json)


def employee_band(count: int | None, range_json: object) -> str:
    """The band the account row shows: the provider's own range, else the band this headcount falls
    in, else ``"Unknown"``.

    The provider's range wins because it is a *stated* fact about the company, while
    :func:`band_for_headcount` is our own bucketing of a number — when both exist they normally
    agree, and when they disagree the source's own words are the honest answer.
    """
    return employee_range_label(range_json) or band_for_headcount(count) or EMPTY_BAND


def location_label(hq_location_json: object) -> str | None:
    """The one line a screen shows for ``core.hq_location``.

    The registry declares an object whose required key is ``raw`` — the source's own words — with
    normalized ``city``/``region``/``country`` beside it. ``raw`` is preferred (it is what the
    source actually said); the normalized parts are joined only when it is missing, and a plain
    string value (which the lenient writer may store) is served as-is. Rendering the whole object
    would put ``"city: Tel Aviv; country: Israel; raw: Tel Aviv, Israel"`` on the row.
    """
    if isinstance(hq_location_json, dict):
        raw = _text(hq_location_json.get("raw"))
        if raw is not None:
            return raw
        parts = [
            part
            for part in (
                _text(hq_location_json.get("city")),
                _text(hq_location_json.get("region")),
                _text(hq_location_json.get("country")),
            )
            if part
        ]
        return ", ".join(parts) if parts else None
    return (
        _text(render_value_text("core.hq_location", hq_location_json)) if hq_location_json else None
    )


def headcount_label(count: int | None, range_: str | None) -> str:
    """``"400 (201-500)"`` when both are known, whichever half exists, else ``"Unknown"``."""
    band = _text(range_)
    if count is not None and band is not None:
        return f"{count} ({band})"
    if count is not None:
        return str(count)
    return band or EMPTY_BAND


def revenue_label(annual_revenue_json: object, revenue_band: str | None) -> str:
    """The rendered ``core.annual_revenue`` claim, else the band, else ``"Unknown"``."""
    rendered = _text(render_value_text("core.annual_revenue", annual_revenue_json))
    return rendered or _text(revenue_band) or EMPTY_BAND


def funding_label(recent_funding_json: object, total_funding_json: object) -> str | None:
    """``"Series B · $50M"`` from the latest round and the running total; whichever exists.

    The round is read as a *key* of the ``account.recent_funding`` object, not by rendering the
    whole value: the object also carries an amount and a date, and "Series B; $30M; 2025-11-02 ·
    $50M" is not a label.
    """
    round_name = (
        _text(recent_funding_json.get("round")) if isinstance(recent_funding_json, dict) else None
    )
    total = _text(render_value_text("account.total_funding", total_funding_json))
    parts = [part for part in (round_name, total) if part]
    return " · ".join(parts) if parts else None


def website_url(domain: str | None) -> str | None:
    """The account's site from its ``primary_domain``; ``None`` when it has none."""
    host = _text(domain)
    return f"https://{host}" if host else None


def website_label(domain: str | None) -> str | None:
    """The bare host a person reads — no scheme, no ``www.``, no path."""
    host = _text(domain)
    if host is None:
        return None
    if "//" in host:
        host = urlsplit(host).hostname or ""
    host = host.split("/")[0].lower().removeprefix("www.")
    return host or None


def industry_labels(industry_json: object, industries_all_json: object) -> list[str]:
    """The primary industry first, then the rest of the list, deduped in order.

    A non-string entry is dropped rather than stringified: ``core.industries_all`` is declared a
    list of strings, and rendering an unexpected object would put ``{'name': …}`` on a chip.
    """
    labels: list[str] = []
    primary = _text(industry_json)
    if primary is not None:
        labels.append(primary)
    if isinstance(industries_all_json, list):
        for entry in industries_all_json:
            label = _text(entry)
            if label is not None and label not in labels:
                labels.append(label)
    return labels


def socials(linkedin_json: object, twitter_json: object) -> list[AccountSocial]:
    """The two social links the account rail shows, each gated on :func:`safe_public_url`."""
    found: list[AccountSocial] = []
    for social_id, label, value in (
        ("linkedin", "LinkedIn", linkedin_json),
        ("twitter", "Twitter", twitter_json),
    ):
        url = _text(value)
        if url is not None and safe_public_url(url):
            found.append(
                AccountSocial(
                    id=social_id, label=cast(Literal["LinkedIn", "Twitter"], label), url=url
                )
            )
    return found


# --- contact rail labels --------------------------------------------------------------------------

_ISO_DATE_CHARS = 10


def _plural(count: int, unit: str) -> str:
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"


def tenure(start: date, *, now: date) -> tuple[str, str]:
    """``("2 years 5 months", "2024-04-01")`` — the served label and the sortable start date.

    Whole calendar months, never negative: a start date in the future reads ``"0 months"`` rather
    than a negative tenure. Singular forms are spelled out, and a zero component is dropped so a
    one-year anniversary reads ``"1 year"`` rather than ``"1 year 0 months"``.
    """
    months = (now.year - start.year) * 12 + (now.month - start.month)
    if now.day < start.day:
        months -= 1
    months = max(0, months)
    years, remainder = divmod(months, 12)
    if years and remainder:
        label = f"{_plural(years, 'year')} {_plural(remainder, 'month')}"
    elif years:
        label = _plural(years, "year")
    else:
        label = _plural(remainder, "month")
    return label, start.isoformat()


def _iso_date(value: object) -> date | None:
    raw = _text(value)
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw[:_ISO_DATE_CHARS])
    except ValueError:
        return None


def current_position_start(career_history_json: object) -> date | None:
    """When the person started the job they are still in, from ``contact.facet.career_history``.

    The current position is the entry with no ``date.end``; when several are open (an advisor role
    alongside a day job) the latest start wins. A history stored as a list of *strings* — which the
    lenient writer also accepts — yields ``None``: there is no start date to be found in prose, and
    inventing one would put a fabricated tenure on the contact header.
    """
    if not isinstance(career_history_json, list):
        return None
    starts: list[date] = []
    for entry in career_history_json:
        if not isinstance(entry, dict):
            continue
        dates = entry.get("date")
        if not isinstance(dates, dict) or dates.get("end") is not None:
            continue
        start = _iso_date(dates.get("start"))
        if start is not None:
            starts.append(start)
    return max(starts) if starts else None


def education_label(alma_mater_json: object) -> str | None:
    """``"Columbia Business School, MBA"`` from the object form, the string itself from the string
    form, and the **first entry** of a list — which is what the answer key actually holds.

    The Zafran walk (D3 close-out) found ``contact.facet.alma_mater`` stored as the provider's list:
    either strings (``["MBA at Columbia Business School (2011 - 2013)", …]``) or objects keyed
    ``school``/``degree`` rather than the registry's ``institution``. The rail has one education
    row, so the first (most recent, as the provider orders them) entry is served; both key
    spellings are read so neither the registered shape nor the provider's is silently blank.
    """
    if isinstance(alma_mater_json, list):
        for entry in alma_mater_json:
            label = education_label(entry)
            if label is not None:
                return label
        return None
    if isinstance(alma_mater_json, dict):
        parts = [
            part
            for part in (
                _text(alma_mater_json.get("institution")) or _text(alma_mater_json.get("school")),
                _text(alma_mater_json.get("degree")),
            )
            if part
        ]
        return ", ".join(parts) if parts else None
    return _text(alma_mater_json)


def linkedin_label(url: str | None) -> str | None:
    """The handle at the end of a LinkedIn URL — ``/in/nicholastfisher`` → ``nicholastfisher``."""
    raw = _text(url)
    if raw is None:
        return None
    segments = [segment for segment in urlsplit(raw).path.split("/") if segment]
    return segments[-1] if segments else None


_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR


def time_label(occurred_at: datetime, *, now: datetime) -> str:
    """A relative label computed against an explicitly passed ``now``.

    Past 30 days the relative form stops being useful and the ISO date is served instead — a date
    the reader can check, rather than "47 days ago", which they would have to do arithmetic on.
    """
    seconds = (now - occurred_at).total_seconds()
    if seconds < _MINUTE:
        return "just now"
    if seconds < _HOUR:
        return f"{_plural(int(seconds // _MINUTE), 'minute')} ago"
    if seconds < _DAY:
        return f"{_plural(int(seconds // _HOUR), 'hour')} ago"
    if seconds < 2 * _DAY:
        return "yesterday"
    if seconds < 30 * _DAY:
        return f"{_plural(int(seconds // _DAY), 'day')} ago"
    return occurred_at.date().isoformat()


# --- email ----------------------------------------------------------------------------------------

#: The two provider verdicts that mean "this address is usable" (``ai_ark_client.EmailVerdict``).
_USABLE_EMAIL_STATUSES = frozenset({"verified_smtp", "catch_all_valid"})

#: The one verdict that means a mailbox was actually probed, and so the only one that may stamp a
#: verification date on the screen.
_SMTP_VERIFIED = "verified_smtp"


@dataclass(frozen=True)
class EmailFacts:
    """What the email chip shows: the state, the address, when it was checked, and its claim id."""

    status: Literal["available", "lookup"]
    label: str | None
    verified_at: str | None
    claim_id: str | None


def _is_addressable(address: str) -> bool:
    """A minimal shape check: the dummy's Zod declares ``emailLabel`` an email.

    A malformed address is served as ``lookup`` with no label rather than failing the whole payload
    on validation — the screen offers a lookup, which is the honest state for an address we cannot
    render.
    """
    local, _, domain = address.partition("@")
    return bool(local) and "." in domain and not domain.startswith(".")


def email_facts(work_email_claim: Claim | None) -> EmailFacts:
    """The email chip's facts from the ``core.work_email`` claim (decision 13)."""
    if work_email_claim is None:
        return EmailFacts(status="lookup", label=None, verified_at=None, claim_id=None)
    claim_id = str(work_email_claim.id)
    value = work_email_claim.value_json
    address = _text(value.get("address")) if isinstance(value, dict) else None
    status = _text(value.get("status")) if isinstance(value, dict) else None
    if status not in _USABLE_EMAIL_STATUSES or address is None or not _is_addressable(address):
        return EmailFacts(status="lookup", label=None, verified_at=None, claim_id=claim_id)
    seen = work_email_claim.observed_at or work_email_claim.collected_at
    return EmailFacts(
        status="available",
        label=address,
        verified_at=seen.date().isoformat() if status == _SMTP_VERIFIED else None,
        claim_id=claim_id,
    )


# --- owners ---------------------------------------------------------------------------------------


_OWNERS_SQL = """
    SELECT user_id, display_name, first_name, last_name
    FROM platform_user
    WHERE user_id IN :user_ids
"""


async def owners_for(conn: AsyncConnection, *, user_ids: Iterable[str]) -> dict[str, AccountOwner]:
    """Resolve workspace user ids to the ``AccountOwner`` shape, in one read.

    The name falls back ``display_name`` → ``"first last"`` → the id itself: an owner chip that
    says ``u_1a2b`` is ugly, but it is true, and it is better than an empty chip on a row whose
    ``owner_user_id`` is set. A user id with no row simply does not come back.
    """
    ids = sorted({user_id for user_id in user_ids if user_id})
    if not ids:
        return {}
    stmt = text(_OWNERS_SQL).bindparams(bindparam("user_ids", expanding=True))
    rows = (await conn.execute(stmt, {"user_ids": ids})).all()
    owners: dict[str, AccountOwner] = {}
    for user_id, display_name, first_name, last_name in rows:
        parts = " ".join(part for part in (first_name, last_name) if part).strip()
        owners[str(user_id)] = AccountOwner(
            id=str(user_id), name=_text(display_name) or parts or str(user_id)
        )
    return owners


# --- custom fields --------------------------------------------------------------------------------

#: How many custom fields the account row shows before the rest fold away (ruling S6).
PRIMARY_CUSTOM_FIELDS = 4

#: The tenant-local registry rows joined to the live claims that fill them.
#:
#: ``workspace_field_definition`` has no ``created_at`` (only ``promoted_at``, which moves when a
#: definition is re-promoted), so "registry order" is ``field_key`` — stable, so which four fields
#: are ``primary`` does not silently change under the user.
#:
#: ``active`` is filtered *and* retirement is joined: the table's own CHECK forbids ``active =
#: false``, so retirement is the mechanism a workspace field actually stops by, exactly as
#: ``list_effective_fields`` resolves it. (That helper is not reused here because
#: ``ResolvedFieldDefinition`` does not carry ``presentation``, which the wire model needs.)
_CUSTOM_FIELDS_SQL = """
    WITH defs AS (
        SELECT w.field_key, w.description, w.presentation
        FROM workspace_field_definition w
        LEFT JOIN workspace_field_retirement r
          ON r.workspace_id = w.workspace_id AND r.field_key = w.field_key
        WHERE w.workspace_id = :definition_workspace_id
          AND w.pack = 'client'
          AND w.active
          AND r.field_key IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM workspace_dynamic_client_kb_erasure e
              WHERE e.workspace_id = w.workspace_id
          )
    )
    SELECT DISTINCT ON (c.entity_id, c.field_key)
        c.entity_id, c.field_key, c.value_json, d.description, d.presentation
    FROM claim c
    JOIN defs d ON d.field_key = c.field_key
    WHERE c.entity_id IN :entity_ids
      AND c.superseded_by IS NULL
      AND ({scope_sql})
    ORDER BY c.entity_id, c.field_key, c.collected_at DESC, c.id DESC
"""


async def custom_fields_for(
    conn: AsyncConnection, *, workspace_id: str, account_ids: Sequence[EntityId]
) -> dict[EntityId, list[AccountCustomField]]:
    """The client-pack custom variables each account actually holds (decision 7).

    A registry row with no live claim on an account does not appear on that account: an empty
    custom field is noise, not information. Where a field has several live claims the newest
    ``collected_at`` wins, matching the merge's own tie-break.
    """
    if not account_ids:
        return {}
    scope_sql, scope_params = WorkspaceScope.for_workspace(workspace_id).predicate()
    stmt = text(_CUSTOM_FIELDS_SQL.format(scope_sql=scope_sql)).bindparams(
        bindparam("entity_ids", expanding=True, type_=PgUUID(as_uuid=True)),
    )
    rows = (
        await conn.execute(
            stmt,
            {
                "definition_workspace_id": workspace_id,
                "entity_ids": list(account_ids),
                **scope_params,
            },
        )
    ).all()

    fields: dict[EntityId, list[AccountCustomField]] = {}
    for entity_id, field_key, raw_value, description, presentation in rows:
        served = fields.setdefault(EntityId(uuid.UUID(str(entity_id))), [])
        served.append(
            AccountCustomField(
                id=str(field_key),
                label=_text(description) or str(field_key),
                value=render_value_text(str(field_key), decode_jsonb_scalar(raw_value)),
                presentation=cast(Presentation, str(presentation)),
                primary=len(served) < PRIMARY_CUSTOM_FIELDS,
            )
        )
    return fields


# --- last modified --------------------------------------------------------------------------------

#: One statement, three sources. Each source is its own CTE joined back to the subject rows, so an
#: account with no claims and no display blocks still reports its ``account_entity.updated_at``
#: instead of dropping out of the result.
_LAST_MODIFIED_SQL = """
    WITH subject AS (
        SELECT id, updated_at
        FROM account_entity
        WHERE workspace_id = :subject_workspace_id AND id IN :entity_ids
    ),
    claim_stamp AS (
        SELECT c.entity_id AS id, MAX(c.collected_at) AS stamp
        FROM claim c
        JOIN subject s ON s.id = c.entity_id
        WHERE c.superseded_by IS NULL AND ({scope_sql})
        GROUP BY c.entity_id
    ),
    block_stamp AS (
        SELECT b.subject_id AS id, MAX(b.generated_at) AS stamp
        FROM display_block b
        JOIN subject s ON s.id = b.subject_id
        WHERE b.workspace_id = :subject_workspace_id
          AND b.subject_kind = 'account'
          AND b.superseded_at IS NULL
        GROUP BY b.subject_id
    )
    SELECT
        s.id,
        GREATEST(
            s.updated_at,
            COALESCE(c.stamp, s.updated_at),
            COALESCE(b.stamp, s.updated_at)
        ) AS last_modified
    FROM subject s
    LEFT JOIN claim_stamp c ON c.id = s.id
    LEFT JOIN block_stamp b ON b.id = s.id
"""


async def last_modified_for(
    conn: AsyncConnection, *, workspace_id: str, account_ids: Sequence[EntityId]
) -> dict[EntityId, datetime]:
    """When each account last changed: the entity row, its claims, or its display (decision 5)."""
    if not account_ids:
        return {}
    scope_sql, scope_params = WorkspaceScope.for_workspace(workspace_id).predicate()
    stmt = text(_LAST_MODIFIED_SQL.format(scope_sql=scope_sql)).bindparams(
        bindparam("entity_ids", expanding=True, type_=PgUUID(as_uuid=True)),
    )
    rows = (
        await conn.execute(
            stmt,
            {
                "subject_workspace_id": workspace_id,
                "entity_ids": list(account_ids),
                **scope_params,
            },
        )
    ).all()
    return {EntityId(uuid.UUID(str(entity_id))): _aware(stamp) for entity_id, stamp in rows}


_CONTACT_LAST_MODIFIED_SQL = """
    SELECT MAX(collected_at) FROM claim
    WHERE entity_id = :contact_id AND superseded_by IS NULL
"""


async def contact_last_modified(
    conn: AsyncConnection, *, contact_id: EntityId, updated_at: datetime
) -> datetime:
    """The contact's own latest claim stamp, else its entity row's (ruling R8).

    The read is keyed on the contact entity and needs no workspace predicate: contacts are
    workspace-local (the B3 ruling — no global contact identity), so every claim on this entity
    belongs to the workspace that owns it. This is an entity-scoped read, not the forbidden
    ``claim.workspace_id``-only one.
    """
    stamp = (
        await conn.execute(text(_CONTACT_LAST_MODIFIED_SQL), {"contact_id": contact_id})
    ).scalar_one_or_none()
    return _aware(stamp) if stamp is not None else updated_at


def _aware(value: datetime) -> datetime:
    """A database timestamp as an aware UTC datetime (the columns are ``timestamptz``)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def iso_utc(value: datetime) -> str:
    """THE contract-v1 timestamp form: UTC, ``Z``-suffixed — ``2026-09-08T12:00:00Z``.

    Zod's ``z.string().datetime()`` — which every v1 timestamp field is declared with — accepts an
    offset only when the schema opts in with ``{offset: true}``, and the vendored schemas do not.
    So ``datetime.isoformat()``'s ``+00:00`` tail, which is what every ``timestamptz`` column
    yields, would be *rejected* by the frontend's own parser. Every v1 serialisation of a datetime
    goes through here, so the whole contract can only speak one dialect. A naive value is read as
    UTC (the columns are ``timestamptz``; a naive one has already lost its zone, and guessing a
    local zone would move the instant).
    """
    return _aware(value).astimezone(UTC).isoformat().replace("+00:00", "Z")


# --- activity -------------------------------------------------------------------------------------

#: The default page of the activity feed (decision 8).
ACTIVITY_LIMIT = 100

_ACTIVITY_SQL = """
    SELECT event_id, kind, actor_kind, actor_user_id, text, action, occurred_at
    FROM account_activity_event
    WHERE workspace_id = :workspace_id AND account_entity_id = :account_id
    ORDER BY occurred_at DESC, event_id DESC
    LIMIT :limit
"""

ActivityKind = Literal["contacts", "summary", "created", "artifact", "updated"]


async def activity_for(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: EntityId,
    limit: int = ACTIVITY_LIMIT,
    now: datetime,
) -> list[AccountActivity]:
    """The account's durable activity feed, newest first (decision 8).

    A person row whose user cannot be resolved is attributed to the id itself rather than dropped:
    the event genuinely had a human actor, and hiding that is a worse lie than an ugly name.
    """
    rows = (
        await conn.execute(
            text(_ACTIVITY_SQL),
            {"workspace_id": workspace_id, "account_id": account_id, "limit": limit},
        )
    ).all()
    if not rows:
        return []
    people = await owners_for(
        conn, user_ids=[str(row[3]) for row in rows if row[2] == "person" and row[3]]
    )

    feed: list[AccountActivity] = []
    for event_id, kind, actor_kind, actor_user_id, body, action, occurred_at in rows:
        actor: ClueActor | PersonActor | None
        if actor_kind == "person" and actor_user_id:
            resolved = people.get(str(actor_user_id))
            actor = PersonActor(
                type="person",
                id=str(actor_user_id),
                name=resolved.name if resolved is not None else str(actor_user_id),
            )
        else:
            actor = ClueActor(type="clue")
        stamp = _aware(occurred_at)
        feed.append(
            AccountActivity(
                id=str(event_id),
                kind=cast(ActivityKind, str(kind)),
                text=str(body),
                time_label=time_label(stamp, now=now),
                actor=actor,
                action=_text(action),
                occurred_at=iso_utc(stamp),
            )
        )
    return feed


# --- research status ------------------------------------------------------------------------------

#: The latest ARV2 job per account, plus the one extra fact the accounts table shows: is this
#: account *being re-researched right now*?
#:
#: One statement, one table. ``arv2_research_job`` carries its own ``workspace_id`` (and its
#: composite FK pins that to the account's own), so joining ``arv2_research_run`` would buy a
#: second table and no extra scoping. The run's ``project_id`` is deliberately not consulted
#: either: an account's research status is the status of *its* latest job, whichever project
#: launched it — an account researched under one project is not unresearched when read under
#: another (D4-b decision 1).
#:
#: ``refreshing`` is true when a **non-terminal** job (``not_started``/``in_progress`` — a
#: ``suspended`` job is halted, not running) is newer than a ``completed`` one for the same
#: account. The ``(created_at, job_id)`` row comparison is the same total order the ``DISTINCT ON``
#: sorts by, so "newer" means one thing in both halves of the row.
_ARV2_RESEARCH_STATUS = text(
    """
    SELECT DISTINCT ON (j.account_entity_id)
        j.account_entity_id,
        j.status,
        EXISTS (
            SELECT 1
            FROM arv2_research_job live
            JOIN arv2_research_job done
              ON done.workspace_id = live.workspace_id
             AND done.account_entity_id = live.account_entity_id
             AND done.status = 'completed'
             AND (done.created_at, done.job_id) < (live.created_at, live.job_id)
            WHERE live.workspace_id = j.workspace_id
              AND live.account_entity_id = j.account_entity_id
              AND live.status IN ('not_started', 'in_progress')
        ) AS refreshing
    FROM arv2_research_job j
    WHERE j.workspace_id = :workspace_id
      AND j.account_entity_id IN :account_ids
    ORDER BY j.account_entity_id, j.created_at DESC, j.job_id DESC
    """
).bindparams(bindparam("account_ids", expanding=True, type_=PgUUID(as_uuid=True)))


async def arv2_research_status_for(
    conn: AsyncConnection, *, workspace_id: str, account_ids: Sequence[EntityId]
) -> dict[EntityId, tuple[ResearchStatus, bool]]:
    """``{account: (status, refreshing)}`` from the R2 rows — ARV2's own truth, nothing else.

    The status is served **verbatim**. ``arv2_research_job.status`` is the seam-1 vocabulary
    (``not_started``/``in_progress``/``needs_review``/``completed``/``suspended``), which is
    character-for-character the contract's
    :data:`~clue_api.frontend_read.contract_v1.ResearchStatus` — so there is no mapping here to
    drift, and no lifecycle to reinterpret. The two vocabularies are pinned equal by a test rather
    than by this comment.

    An account with **no** job is simply absent from the result: "never researched" is a fact
    about a missing row, and the callers spell it ``("not_started", False)`` at the one place they
    build the row. Returning it here would make an unresearched account indistinguishable from one
    holding a genuine ``not_started`` job.
    """
    if not account_ids:
        return {}
    rows = (
        await conn.execute(
            _ARV2_RESEARCH_STATUS,
            {"workspace_id": workspace_id, "account_ids": list(account_ids)},
        )
    ).all()
    return {
        EntityId(uuid.UUID(str(account_id))): (cast(ResearchStatus, str(status)), bool(refreshing))
        for account_id, status, refreshing in rows
    }


# --- research evidence ----------------------------------------------------------------------------


async def research_evidence_for(
    conn: AsyncConnection, *, workspace_id: str, claim_ids: Iterable[str]
) -> list[ResearchEvidence]:
    """D2's evidence refs with the two read-layer overrides of decision 9.

    ``sourceUrl`` survives only if it is a safe public URL — a ``file://`` snapshot path or a
    credentialed URL is dropped to ``null``, which the contract already permits and which the
    drawer renders as a record rather than a broken link. ``provider`` is mapped to its display
    name. Everything else is D2's, unchanged: this layer relabels, it does not re-derive.
    """
    ids = list(claim_ids)
    if not ids:
        return []
    refs = await evidence_for_ids(conn, workspace_id=workspace_id, claim_ids=ids)
    served: list[ResearchEvidence] = []
    for ref in refs:
        wire: dict[str, Any] = dict(ref.to_wire())
        source_url = wire.get("sourceUrl")
        if not (isinstance(source_url, str) and safe_public_url(source_url)):
            wire["sourceUrl"] = None
        provider = wire.get("provider")
        if isinstance(provider, str):
            wire["provider"] = PROVIDER_LABELS.get(provider, provider)
        served.append(ResearchEvidence.model_validate(wire))
    return served
