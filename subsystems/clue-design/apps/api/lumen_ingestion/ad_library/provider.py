"""The ad-library provider seam (ruling D3) — one protocol, typed pages, no vendor names.

Everything downstream of this module works in :class:`AdLibraryAd` / :class:`AdLibraryPage`
and never learns which vendor answered. Swapping the v1 vendor for another (or adding a Meta
/ Google fetcher, spec §7) is a new :class:`AdLibraryProvider` implementation plus a line in
:func:`resolve_provider` — never a change to harvest, custody, distillation or the job.

**Credentials are environment-only.** A provider that has none raises
:class:`AdLibraryCredentialsMissing` from its constructor: the harvest fails loudly and
immediately rather than issuing an unauthenticated call whose 401 body would then have to be
guessed at. Nothing in this package ever logs a key, and the typed error's message names the
variables to set, never their values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "AdLibraryAd",
    "AdLibraryCredentialsMissing",
    "AdLibraryError",
    "AdLibraryPage",
    "AdLibraryProvider",
    "resolve_provider",
]

JsonObject = dict[str, Any]


class AdLibraryError(RuntimeError):
    """A typed ad-library failure. ``code`` is the stable, loggable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AdLibraryCredentialsMissing(AdLibraryError):
    """The configured provider has no credentials in the environment.

    Deliberately raised at construction, before any request is built: an ad-library call
    costs a vendor credit, and a call we already know is unauthenticated is a call worth not
    making. The message names the environment variables and never their values.
    """

    def __init__(self, provider: str, variables: tuple[str, ...]) -> None:
        super().__init__(
            "ad_library.credentials_missing",
            f"the {provider} ad-library provider needs {' and '.join(variables)} set in the "
            "environment; credentials are never read from code or from the repository",
        )
        self.provider = provider
        self.variables = variables


@dataclass(frozen=True)
class AdLibraryAd:
    """One ad as the seam models it — the vendor's wire shape, normalized and narrowed.

    ``creative_type`` and ``kind`` are kept apart because they answer different questions:
    ``kind`` is the coarse media class the filter reads (``image`` / ``video`` /
    ``carousel`` / ``document``), while ``creative_type`` is the vendor's own richer label,
    carried through only as provenance.

    ``advertiser_name`` matters as much as the media class. A company page's ad library also
    serves *personal thought-leader promotions* — a named individual's post, promoted by the
    company — and those are not the brand's creative system (spec §4.1). The advertiser name
    is the only field that separates them, so it is a first-class member here rather than a
    detail buried in ``raw``.
    """

    ad_id: str
    kind: str
    creative_type: str | None
    advertiser_name: str | None
    advertiser_promoted: bool
    image_url: str | None
    image_alt_text: str | None
    headline_title: str | None
    headline_description: str | None
    commentary_text: str | None
    view_details_link: str | None
    has_carousel: bool

    @classmethod
    def from_wire(cls, record: JsonObject) -> "AdLibraryAd":
        """Read one vendor ad record defensively.

        Every nested block (``advertiser``, ``image``, ``headline``, ``commentary``) is
        optional and is served as an explicit ``null`` by the real endpoint on some ads, so
        each is coerced through ``or {}`` rather than indexed. A record with no usable
        ``ad_id`` still constructs — the filter drops it — because raising here would turn
        one malformed row into a whole failed page.
        """
        advertiser = record.get("advertiser") or {}
        image = record.get("image") or {}
        headline = record.get("headline") or {}
        commentary = record.get("commentary") or {}
        return cls(
            ad_id=str(record.get("ad_id") or ""),
            kind=str(record.get("type") or "").strip().lower(),
            creative_type=_optional_str(record.get("creative_type")),
            advertiser_name=_optional_str(advertiser.get("name")),
            advertiser_promoted=bool(advertiser.get("promoted")),
            image_url=_optional_str(image.get("url")),
            image_alt_text=_optional_str(image.get("alt_text")),
            headline_title=_optional_str(headline.get("title")),
            headline_description=_optional_str(headline.get("description")),
            commentary_text=_optional_str(commentary.get("text")),
            view_details_link=_optional_str(record.get("view_details_link")),
            has_carousel=bool(record.get("carousel")),
        )


@dataclass(frozen=True)
class AdLibraryPage:
    """One page of results plus the cursor that reaches the next one.

    ``continuation_token`` and ``is_last_page`` are BOTH carried and BOTH honoured by the
    pagination loop: the real endpoint keeps returning a token past the end of the useful
    results (Ramp page 2 answered ``total_ads: 0`` with a fresh token and
    ``is_last_page: false``), so a loop that trusted only the token would spend a credit per
    empty page until its page cap saved it.
    """

    page_id: str | None
    total_ads: int | None
    ads: tuple[AdLibraryAd, ...]
    continuation_token: str | None
    is_last_page: bool
    provider: str
    raw_meta: JsonObject = field(default_factory=dict)


@runtime_checkable
class AdLibraryProvider(Protocol):
    """Fetch one bounded page of an advertiser's published ads.

    One page, one call, one credit — pagination is the caller's bounded loop
    (:func:`lumen_ingestion.ad_library.harvest.harvest_creatives`), never the provider's, so
    the spend stays visible and capped at the call site that decided to make it.
    """

    #: The stable provider label stamped into every creative's provenance.
    name: str

    def fetch_page(
        self,
        *,
        company_domain: str | None = None,
        page_id: str | None = None,
        continuation_token: str | None = None,
        date_filter: str | None = None,
    ) -> AdLibraryPage: ...


def resolve_provider(name: str = "adyntel") -> AdLibraryProvider:
    """The one place a vendor is named. Raises for an unknown provider, loudly.

    Imported lazily so this module — the seam every other module imports — never pulls a
    concrete vendor (or its transport) into a process that only wanted the types.
    """
    if name == "adyntel":
        from .adyntel import AdyntelProvider

        return AdyntelProvider()
    raise AdLibraryError(
        "ad_library.unknown_provider",
        f"no ad-library provider named {name!r} is registered (v1 ships 'adyntel')",
    )


def _optional_str(value: Any) -> str | None:
    """``None`` for absent/blank, a stripped string otherwise. Never ``"None"``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
