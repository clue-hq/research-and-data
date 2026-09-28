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

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.evidence import evidence_for_ids
from clue_api.arv2.display.personas import (
    PERSONA_LABELS,
    PERSONA_RANK,
    persona_display,
    persona_label,
    persona_rank,
)
from clue_api.arv2.display.render import render_value_text
from clue_api.arv2.logo_resolution import brandfetch_logo_url, is_linkedin_mark
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
from clue_api.url_safety import safe_public_url
from clue_config import Settings
from clue_core import Claim, ClaimId, EntityId, decode_jsonb_scalar
from clue_research.claimstore import WorkspaceScope, claims_by_ids
from clue_research.compliance import WorkspacePolicy

__all__ = [
    "EMPTY_BAND",
    "INFLUENCE_DEFAULTS",
    "PERSONA_LABELS",
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
    "custom_field_evidence_for",
    "education_label",
    "email_facts",
    "employee_band",
    "employee_range_label",
    "fit_band",
    "fit_score_100",
    "format_money",
    "funding_label",
    "headcount_label",
    "industry_labels",
    "iso_utc",
    "location_label",
    "last_modified_for",
    "linkedin_label",
    "owners_for",
    "persona_display",
    "persona_label",
    "persona_rank",
    "research_evidence_for",
    "revenue_band_label",
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

    from clue_research.compliance.display import research_display_allowed

    return research_display_allowed(
        entity_type=claim.entity_type,
        use_class=claim.use_class,
        outreach_safe=claim.outreach_safe,
        policy=policy,
    )


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


#: The symbol a currency prints as. A code outside this map is written as a prefix instead
#: (``"INR 12M"``) — a code a marketer can read beats a symbol we would have to guess at.
_CURRENCY_SYMBOLS: dict[str, str] = {"USD": "$", "EUR": "€", "GBP": "£"}

#: Compact money units, largest first. One decimal at most: ``$130.5M`` is a figure, ``$130.53M``
#: is a spreadsheet cell.
_MONEY_UNITS: tuple[tuple[int, str], ...] = ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K"))

#: The range separator on a revenue band — an en dash, not a hyphen.
_RANGE_DASH = "–"


def _number(value: object) -> float | None:
    """``value`` as a positive number, from an int, a float or a numeric string; else ``None``.

    ``bool`` is excluded explicitly (it is an ``int`` in Python and ``True`` is not one dollar), and
    so is a non-positive amount: a company with zero or negative revenue is a bad row, not a small
    company — the same reading :func:`band_for_headcount` gives a headcount below 1.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().replace(",", ""))
        except ValueError:
            return None
    else:
        return None
    return number if number > 0 else None


def _compact(amount: float) -> str:
    """``10000000`` → ``"10M"``; ``130500000`` → ``"130.5M"``; ``900`` → ``"900"``. No symbol."""
    for size, unit in _MONEY_UNITS:
        if amount >= size:
            scaled = round(amount / size, 1)
            whole = int(scaled)
            return f"{whole}{unit}" if scaled == whole else f"{scaled}{unit}"
    whole = int(round(amount))
    return str(whole)


def _symbol(currency: object) -> str:
    """The prefix ``currency`` prints as: a symbol, a code, or nothing when we were not told.

    An unknown currency yields the **empty** prefix rather than ``"$"``. Defaulting to a dollar
    sign would turn an amount the provider never denominated into a dollar figure — a small
    fabrication on a card a marketer quotes in an email — so a bare ``"60M"`` is the honest answer.
    """
    code = _text(currency)
    if code is None:
        return ""
    code = code.upper()
    return _CURRENCY_SYMBOLS.get(code) or f"{code} "


def format_money(amount: object, currency: object) -> str | None:
    """``(130500000, "USD")`` → ``"$130.5M"``; ``(12000000, "INR")`` → ``"INR 12M"``.

    ``None`` for anything that is not a positive number, so a caller can fall through to whatever
    it holds instead of printing ``"None"`` or the raw object at a marketer.
    """
    number = _number(amount)
    return None if number is None else f"{_symbol(currency)}{_compact(number)}"


#: The unit letter a ``core.revenue_band`` token spells, and the letter a screen prints.
_BAND_UNITS: dict[str, str] = {"k": "K", "m": "M", "b": "B"}

#: One bound of a band token: ``"10m"``, ``"500m"``, ``"1b"``, or a bare number of dollars.
_BAND_BOUND = re.compile(r"(\d+(?:\.\d+)?)([kmb])?\Z")


def _band_bound(token: str) -> str | None:
    """One side of a band token as a figure — ``"10m"`` → ``"10M"``; ``"250000"`` → ``"250K"``."""
    match = _BAND_BOUND.match(token)
    if match is None:
        return None
    number, unit = match.group(1), match.group(2)
    if unit is not None:
        return f"{number}{_BAND_UNITS[unit]}"
    parsed = _number(number)
    return None if parsed is None else _compact(parsed)


def revenue_band_label(value: str | None) -> str:
    """A ``core.revenue_band`` token as the words a screen prints (D4-b controller ruling 2).

    The field is a closed vocabulary of range tokens — ``under_1m``, ``1m_10m``, ``10m_50m``,
    ``50m_100m``, ``100m_500m``, ``500m_1b``, ``1b_plus`` (``REVENUE_BAND_OPTIONS``) — and the
    accounts list was serving them verbatim, so a marketer read ``"10m_50m"`` in the revenue
    column. Three forms are parsed: ``<lo>_<hi>`` → ``"$10M–50M"``, ``<n>_plus`` → ``"$1B+"``,
    ``under_<n>`` → ``"under $1M"``.

    The ``$`` is not an assumption here the way it would be on a raw amount: the band vocabulary is
    *defined* in USD (``account_field_derivation._REVENUE_BAND_CEILINGS``, "exclusive, USD"), so the
    currency is part of what the token means.

    A token this does not recognise is served **as written** — an unregistered band is still the
    row's own value, and inventing a range for it would be worse than an ugly string. An absent
    band is :data:`EMPTY_BAND`.
    """
    token = _text(value)
    if token is None:
        return EMPTY_BAND
    lowered = token.lower()
    if lowered.startswith("under_"):
        bound = _band_bound(lowered.removeprefix("under_"))
        return f"under ${bound}" if bound else token
    if lowered.endswith("_plus"):
        bound = _band_bound(lowered.removesuffix("_plus"))
        return f"${bound}+" if bound else token
    low, _, high = lowered.partition("_")
    if not high:
        return token
    low_label, high_label = _band_bound(low), _band_bound(high)
    if low_label is None or high_label is None:
        return token
    return f"${low_label}{_RANGE_DASH}{high_label}"


def revenue_label(annual_revenue_json: object, revenue_band: str | None) -> str:
    """What the revenue row says, read from the ``core.annual_revenue`` **object** (decision 5).

    The registry stores a provider estimate as ``{"amount_min": …, "amount_max": …, "currency": …,
    "as_of": …, "estimate_kind": …}``. Rendering that generically put
    ``"amount_max: 25000000; amount_min: 10000000; as_of: 2026-08-22; …"`` on the account page —
    a pipeline string, which the founder's D4-b ruling forbids on a screen. So the shape is read:

    * both bounds → ``"$10M–25M"`` — the symbol once, the unit on each side, so a range that
      crosses a unit still reads (``"$750K–1.2M"``);
    * one bound → ``"$10M+"`` (a floor) or ``"up to $25M"`` (a ceiling);
    * a single ``amount`` → :func:`format_money`;
    * a plain string (the lenient writer does not enforce the value schema) → itself.

    Failing all of that, the ``core.revenue_band`` claim **as a label** (never the raw
    ``"10m_50m"`` token — see :func:`revenue_band_label`), then ``"Unknown"``. Nothing is invented:
    an object whose numbers do not parse falls through exactly like a missing claim.
    """
    if isinstance(annual_revenue_json, dict):
        rendered = _revenue_from_object(annual_revenue_json)
        if rendered is not None:
            return rendered
    else:
        stated = _text(annual_revenue_json)
        if stated is not None:
            return stated
    return revenue_band_label(revenue_band)


def _revenue_from_object(value: Mapping[str, Any]) -> str | None:
    """The band or point estimate inside a ``core.annual_revenue`` object; ``None`` when neither."""
    symbol = _symbol(value.get("currency"))
    low = _number(value.get("amount_min"))
    high = _number(value.get("amount_max"))
    if low is not None and high is not None:
        return f"{symbol}{_compact(low)}{_RANGE_DASH}{_compact(high)}"
    if low is not None:
        return f"{symbol}{_compact(low)}+"
    if high is not None:
        return f"up to {symbol}{_compact(high)}"
    return format_money(value.get("amount"), value.get("currency"))


def _round_name(value: object) -> str | None:
    """A funding round as a person names it: ``"SERIES_C"`` → ``"Series C"``; ``"Series B"`` stays.

    The provider's own records name the round in the pipeline's shouting form; the registry sketch
    names it in words. Only the shouting form is rewritten (all upper case, or carrying an
    underscore) so a rationale-style name — ``"Series C extension"`` — is served exactly as written.
    """
    name = _text(value)
    if name is None:
        return None
    if name == name.upper() or "_" in name:
        return name.replace("_", " ").title()
    return name


def _recent_round(value: object, *, currency: object = None) -> str | None:
    """The latest funding round as one phrase — ``"Series C · $60M"`` — or ``None``.

    Three shapes reach this, all of them real. The registry sketch is one object
    (``{"round", "amount", "currency", "date", "investors"}``); the provider's own record (what the
    answer key stores for Zafran) is a **list** of rounds keyed ``{"type", "raised_amount",
    "announced_at", "investors"}``, newest first but not guaranteed so — the latest announcement
    wins, and a list with no dates keeps its own order; a prose value is served as the sentence it
    is. The round name alone, or the amount alone, is served when only one of them is known.

    ``currency`` is the sibling ``account.total_funding`` object's currency, used only when the
    round states none of its own — see :func:`funding_label`.
    """
    if isinstance(value, list):
        rounds = [item for item in value if isinstance(item, dict)]
        if not rounds:
            return None
        latest = max(
            enumerate(rounds),
            key=lambda pair: (
                _text(pair[1].get("announced_at")) or _text(pair[1].get("date")) or "",
                -pair[0],
            ),
        )[1]
        return _recent_round(latest, currency=currency)
    if isinstance(value, dict):
        name = _round_name(value.get("round") or value.get("type"))
        money = _money_of(value, currency=currency)
        parts = [part for part in (name, money) if part is not None]
        return " · ".join(parts) if parts else None
    return _text(value)


def _money_of(value: Mapping[str, Any], *, currency: object = None) -> str | None:
    """The amount inside a funding object, under whichever of its three keys carries it.

    ``amount`` is the registry's key and ``raised_amount`` the provider's; ``amount_usd`` is what
    the synthesis lane writes, and it states its own currency in its name — so it is the one key
    that does not consult the object's ``currency``. ``currency`` is the fallback denomination for
    the first two keys when the object itself names none.
    """
    for key in ("amount", "raised_amount"):
        if value.get(key) is not None:
            return format_money(value.get(key), value.get("currency") or currency)
    return format_money(value.get("amount_usd"), "USD")


def _total_funding(value: object) -> str | None:
    """The running total as money — ``{"amount": 130500000, "currency": "USD", …}`` → ``"$130.5M"``.

    A prose value is served as the sentence it is.
    """
    return _money_of(value) if isinstance(value, dict) else _text(value)


def _stated_currency(total_funding_json: object) -> object:
    """The currency the ``account.total_funding`` object is denominated in, or ``None``.

    ``amount_usd`` counts: the key states its own denomination, so an object carrying only that one
    is a USD object.
    """
    if not isinstance(total_funding_json, dict):
        return None
    stated = _text(total_funding_json.get("currency"))
    if stated is not None:
        return stated
    return "USD" if total_funding_json.get("amount_usd") is not None else None


def funding_label(recent_funding_json: object, total_funding_json: object) -> str | None:
    """``"Series C · $60M · $130.5M"`` — the latest round, then the running total.

    Whichever half exists is served alone; ``None`` when neither says anything. Both halves are
    read out of their registry **objects** rather than rendered generically, for the same reason
    :func:`revenue_label` is: ``"amount: 130500000; currency: USD; investors: 9; rounds: 4"`` is a
    pipeline string, not a label.

    **A round with no currency of its own borrows the total's** (D4-b controller ruling 1). The
    provider's round objects carry ``raised_amount`` and no ``currency`` while the sibling total
    states one; they are the same account's funding in the same provider record, so reading one
    denomination off the other is a fact about that record, not a guess — and it is what stops the
    label reading ``"Series C · 60M · $130.5M"``. When *neither* half names a currency the amounts
    stay bare, because then there is nothing to read it off.
    """
    parts = [
        part
        for part in (
            _recent_round(recent_funding_json, currency=_stated_currency(total_funding_json)),
            _total_funding(total_funding_json),
        )
        if part is not None
    ]
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
#: The other three the registry admits — ``invalid``, ``unknown``, ``unverified`` — all mean the
#: address is not one the screen may offer, so they read as *look this up*, exactly like no claim
#: at all. The claim id still travels, because the chip's evidence hover is about the claim.
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


def _checked_on(value: Mapping[str, Any], claim: Claim) -> str:
    """The day the mailbox was probed: the provider's own timestamp, else when we saw the claim.

    ``checked_at`` is the provider's ISO string, kept verbatim at write time; only its date is
    shown. A value the provider never sent (or sent unparseably) falls back to the claim's own
    observation time rather than dropping the date — the chip says *verified*, so it owes a day.
    """
    checked_at = _text(value.get("checked_at"))
    if checked_at is not None:
        with suppress(ValueError):
            return datetime.fromisoformat(checked_at).date().isoformat()
    seen = claim.observed_at or claim.collected_at
    return seen.date().isoformat()


def email_facts(work_email_claim: Claim | None) -> EmailFacts:
    """The email chip's facts from the ``core.work_email`` claim (decision 13).

    The value is the ``{address, status, checked_at?}`` object every writer produces since D4-b.
    A bare address string — every row written before that — is *not* upgraded here: an address with
    no verdict is an address nobody graded, so it reads as *look this up*, which is the fail-closed
    direction. ``scripts/load_arv2_answer_key.py --repair-emails`` is how a legacy row gains its
    verdict; the reader never invents one.
    """
    if work_email_claim is None:
        return EmailFacts(status="lookup", label=None, verified_at=None, claim_id=None)
    claim_id = str(work_email_claim.id)
    value = work_email_claim.value_json
    if not isinstance(value, dict):
        return EmailFacts(status="lookup", label=None, verified_at=None, claim_id=claim_id)
    address = _text(value.get("address"))
    status = _text(value.get("status"))
    if status not in _USABLE_EMAIL_STATUSES or address is None or not _is_addressable(address):
        return EmailFacts(status="lookup", label=None, verified_at=None, claim_id=claim_id)
    return EmailFacts(
        status="available",
        label=address,
        verified_at=(_checked_on(value, work_email_claim) if status == _SMTP_VERIFIED else None),
        claim_id=claim_id,
    )


# --- owners ---------------------------------------------------------------------------------------


_OWNERS_SQL = """
    SELECT user_id, display_name, first_name, last_name
    FROM platform_user
    WHERE user_id IN :user_ids
"""


#: Where the accounts screens fetch a STORED mark from: the platform's own logo route behind the
#: frontend's BFF mount (a rooted path; session-authenticated like every other BFF path, which is
#: why the frontend renders it with Next's optimizer off). Brandfetch's Logo API URL is the
#: other shape ``logo_path`` can take — an absolute URL the browser embeds directly, because that
#: CDN refuses programmatic fetches by design.
LOGO_PATH_PREFIX = "/api/clue/frontend/v1/accounts"


def account_logo_path(
    account_id: object, logo_url: object, *, domain: object = None, settings: Settings | None = None
) -> str | None:
    """The logo the screens show for an account, or ``None`` for the placeholder.

    Founder rulings 2026-09-11 (supersede D0 ruling S2): a stored LinkedIn mark
    (``core.logo_url``) is served through the platform's logo route; an account with no stored
    mark but a domain gets Brandfetch's **Logo API** URL for that domain (``type/icon``, a
    lettermark when the brand has no icon) when a client id is configured; otherwise ``None``.
    The screens never receive a stored third-party URL — only the route, or the embed-only CDN
    URL that is a pure function of the domain.
    """
    if isinstance(logo_url, str) and is_linkedin_mark(logo_url):
        return f"{LOGO_PATH_PREFIX}/{account_id}/logo"
    if settings is not None and isinstance(domain, str) and domain:
        return brandfetch_logo_url(domain, client_id=settings.brandfetch_client_id)
    return None


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
#: Preserve the established ``field_key`` ordering, so which four fields are ``primary`` does
#: not change when the human edits a research instruction or label.
#:
#: ``active`` is filtered *and* retirement is joined: the table's own CHECK forbids ``active =
#: false``, so retirement is the mechanism a workspace field actually stops by, exactly as
#: ``list_effective_fields`` resolves it. (That helper is not reused here because
#: this is a bulk latest-value projection, rather than a catalog read.)
_CUSTOM_FIELDS_SQL = """
    WITH defs AS (
        SELECT w.field_key, w.description, w.presentation, w.label, w.client_kb_role
        FROM workspace_field_definition w
        LEFT JOIN workspace_field_retirement r
          ON r.workspace_id = w.workspace_id AND r.field_key = w.field_key
        WHERE w.workspace_id = :definition_workspace_id
          AND ((w.pack = 'client' AND :entity_kind = 'account') OR
               (w.client_kb_role = 'research' AND w.field_key LIKE :field_prefix))
          AND w.active
          -- Fields a research agent registered for its own narrative (committee selection,
          -- research findings) are research data, never Custom fields (founder, 2026-09-29).
          AND NOT (w.client_kb_role = 'research' AND w.promoted_by LIKE 'agent:%')
          AND (CAST(:include_retired AS boolean) OR r.field_key IS NULL)
          AND NOT EXISTS (
              SELECT 1 FROM workspace_dynamic_client_kb_erasure e
              WHERE e.workspace_id = w.workspace_id
          )
    )
    SELECT DISTINCT ON (c.entity_id, c.field_key)
        c.entity_id, c.field_key, c.value_json, d.description, d.presentation,
        d.label, d.client_kb_role, c.id
    FROM claim c
    JOIN defs d ON d.field_key = c.field_key
    WHERE c.entity_id IN :entity_ids
      AND c.superseded_by IS NULL
      AND c.entity_type::text = :entity_kind
      AND (d.client_kb_role <> 'research' OR
           (c.reuse_scope = 'tenant_private' AND c.workspace_id = :definition_workspace_id))
      AND ({scope_sql})
    ORDER BY c.entity_id, c.field_key, c.collected_at DESC, c.id DESC
"""


async def custom_fields_for(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_ids: Sequence[EntityId],
    entity_kind: Literal["account", "contact"] = "account",
    include_retired: bool = False,
    policy: WorkspacePolicy | None = None,
) -> dict[EntityId, list[AccountCustomField]]:
    """Scoped custom values with their claim references, including legacy client-pack variables.

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
                "entity_kind": entity_kind,
                "field_prefix": f"{entity_kind}.%",
                "include_retired": include_retired,
                **scope_params,
            },
        )
    ).all()

    allowed: set[str] | None = None
    if entity_kind == "contact":
        if policy is None:
            raise ValueError("Contact custom fields require the workspace display policy.")
        claims = await claims_by_ids(
            conn,
            [ClaimId(row[7]) for row in rows],
            scope=WorkspaceScope.for_workspace(workspace_id),
        )
        allowed = {str(key) for key, claim in claims.items() if arv2_display_allowed(claim, policy)}
    fields: dict[EntityId, list[AccountCustomField]] = {}
    for entity_id, field_key, raw_value, description, presentation, label, role, claim_id in rows:
        if allowed is not None and str(claim_id) not in allowed:
            continue
        served = fields.setdefault(EntityId(uuid.UUID(str(entity_id))), [])
        served.append(
            AccountCustomField(
                id=str(field_key),
                label=(
                    _text(label) or str(field_key).rsplit(".", 1)[-1].replace("_", " ").capitalize()
                )
                if role == "research"
                else _text(description) or str(field_key),
                value=render_value_text(str(field_key), decode_jsonb_scalar(raw_value)),
                presentation=cast(Presentation, str(presentation)),
                primary=len(served) < PRIMARY_CUSTOM_FIELDS,
                claim_id=str(claim_id),
            )
        )
    return fields


async def custom_field_evidence_for(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_id: EntityId,
    entity_kind: Literal["account", "contact"] = "account",
    policy: WorkspacePolicy | None = None,
) -> list[ResearchEvidence]:
    """Retirement hides the column, not its evidence. Erasure and subject policy still apply.

    Used by both the detail payload and artifact authorization, independent of generated prose.
    """
    fields = await custom_fields_for(
        conn,
        workspace_id=workspace_id,
        account_ids=[subject_id],
        entity_kind=entity_kind,
        include_retired=True,
        policy=policy,
    )
    keys = {field.claim_id: field.id for field in fields.get(subject_id, ()) if field.claim_id}
    evidence = await research_evidence_for(conn, workspace_id=workspace_id, claim_ids=keys)
    return [
        record.model_copy(update={"research_field_key": keys[record.claim_id]})
        for record in evidence
    ]


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
#:
#: **Account jobs only.** Since R3 the same table carries the account's *person* jobs
#: (``subject_type = 'person'``, one per committee member, each stamped with the account it belongs
#: to and typically created after the account job finished). An account's research status is the
#: status of its latest **account** job: a committee member still being researched, or one queued
#: and never run, is not the account un-researched, and must not light the account's spinner.
_ARV2_RESEARCH_STATUS = text(
    """
    SELECT DISTINCT ON (j.account_entity_id)
        j.account_entity_id,
        j.job_id,
        j.status,
        EXISTS (
            SELECT 1
            FROM arv2_research_job live
            JOIN arv2_research_job done
              ON done.workspace_id = live.workspace_id
             AND done.account_entity_id = live.account_entity_id
             AND done.subject_type = 'account'
             AND done.status = 'completed'
             AND (done.created_at, done.job_id) < (live.created_at, live.job_id)
            WHERE live.workspace_id = j.workspace_id
              AND live.account_entity_id = j.account_entity_id
              AND live.subject_type = 'account'
              AND live.status IN ('not_started', 'in_progress')
        ) AS refreshing
    FROM arv2_research_job j
    WHERE j.workspace_id = :workspace_id
      AND j.account_entity_id IN :account_ids
      AND j.subject_type = 'account'
    ORDER BY j.account_entity_id, j.created_at DESC, j.job_id DESC
    """
).bindparams(bindparam("account_ids", expanding=True, type_=PgUUID(as_uuid=True)))


async def arv2_research_status_for(
    conn: AsyncConnection, *, workspace_id: str, account_ids: Sequence[EntityId]
) -> dict[EntityId, tuple[ResearchStatus, bool]]:
    """``{account: (status, refreshing)}`` from jobs and their persisted publications.

    Only ``subject_type = 'account'`` rows count: R3's person jobs share the table and the account
    column, and a person still being researched is not an account being re-researched.

    Researcher-owned jobs display completed once required pages are published, even when
    execution bookkeeping needs review. Durable execution status remains untouched. Older
    flows retain their original status projection.

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
    from clue_api.arv2.quality_progress import delivery_progress

    deliveries = await delivery_progress(
        conn, workspace_id=workspace_id, job_ids=[row.job_id for row in rows]
    )
    result: dict[EntityId, tuple[ResearchStatus, bool]] = {}
    for row in rows:
        delivery = deliveries.get(row.job_id)
        status = cast(ResearchStatus, str(row.status))
        refreshing = bool(row.refreshing)
        if delivery is not None:
            if delivery.ready:
                status, refreshing = "completed", False
            elif status == "completed":
                status = "needs_review"
        result[EntityId(uuid.UUID(str(row.account_entity_id)))] = (status, refreshing)
    return result


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
    # A value argument exposes its account-side support as inspectable source cards too.
    # This is a bounded reference expansion, not an extraction or a model call.
    seen = {r.claim_id for r in refs}
    for _ in range(3):
        support_ids = sorted({cid for r in refs for cid in r.supporting_claim_ids} - seen)
        if not support_ids:
            break
        extra = await evidence_for_ids(conn, workspace_id=workspace_id, claim_ids=support_ids[:300])
        refs.extend(extra)
        seen.update(support_ids)
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
