"""Contract v1 — the wire models for the five accounts-screen payloads (ARV2 D3).

This module is the backend half of one contract whose *presentation truth* is the frontend's own
Zod: ``apps/frontend/src/features/accounts/model/*.ts``, carrying the D0/D3 amendments (they were
vendored under ``tests/api/contract_v1/zod/`` until the D4 re-lift landed them in the monorepo).
``tests/api/contract_v1/test_contract_v1.py`` holds the two sides together:

* every model's alias set equals its Zod schema's field set, and
* a field required on one side is required on the other.

The human-readable statement of the same contract — sources, backend-owned semantics, what is
deliberately *not* on the wire — is ``apps/frontend/docs/api-contracts/accounts.md § Contract v1``,
whose field tables the same test checks against these models.

**Three rules govern every field here, and they are the whole reason this module is hand-written
rather than generated.**

1. **Required-but-nullable is not optional.** A Zod ``.nullable()`` without a default means "the
   backend must decide, and ``null`` is a legitimate decision" — an unscored account's
   ``fitScore``, a domainless account's ``websiteUrl``. Its pydantic twin is ``X | None`` with **no
   default**, so a serving code path that forgets it fails loudly instead of shipping a silent
   ``null``.
2. **An unknown optional is omitted, never ``null``.** Most optional fields here are Zod
   ``.optional()`` *without* ``.nullable()``, and Zod rejects an explicit ``null`` for those. They
   therefore carry ``Field(default=None, exclude_if=_is_none)`` — the convention already in
   ``accounts_list.AccountListMeta`` — so an absent value is absent from the JSON. The handful that
   Zod declares ``.nullish()`` / ``.nullable().default(null)`` (``owner``, ``createdBy``,
   ``primaryProjectId``, ``sendLine``, ``emailClaimId``) are plain ``= None`` and do serialize as
   ``null``.
3. **No display string is invented here.** These are transport shapes only; the semantics — what
   ``verifiedAt`` means, how ``priority`` is chosen, when a section is ``restricted`` — belong to
   the "Backend-owned semantics" table in ``accounts.md`` and to the composition code that fills
   these models in.

Nothing in this module reads the database, and it deliberately imports no other ``frontend_read``
surface: it is the vocabulary the D3 endpoints are written against, not an endpoint itself.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

__all__ = [
    "V1_PAYLOADS",
    "AccountActivity",
    "AccountArtifact",
    "AccountContact",
    "AccountContactDetailResponseV1",
    "AccountContactDetailV1",
    "AccountContactSummaryV1",
    "AccountContactsMeta",
    "AccountContactsResponseV1",
    "AccountCustomField",
    "AccountDetailResponseV1",
    "AccountDetailV1",
    "AccountFit",
    "AccountFitCriterion",
    "AccountInsight",
    "AccountOwner",
    "AccountProject",
    "AccountSocial",
    "AccountV1",
    "AccountWorkspaceResponseV1",
    "AccountWorkspaceV1",
    "AccountsMeta",
    "AccountsResponseV1",
    "BuyingCommitteeMember",
    "ClueActor",
    "ContactEvidence",
    "HttpUrl",
    "PersonActor",
    "ResearchContactReference",
    "ResearchDisplayBlock",
    "ResearchEvidence",
    "ResearchInlineSegment",
    "ResearchItem",
    "ResearchSection",
    "ResearchSendLine",
    "ResearchSentence",
    "ResearchStatus",
    "V1Model",
    "WorkspaceInsight",
]


# --- shared scalars ---------------------------------------------------------------------------


def _http_url(value: str) -> str:
    """Mirror the dummy's ``HttpUrlSchema``: a parseable ``http``/``https`` absolute URL."""
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("Expected an HTTP(S) URL")
    return value


def _asset_path(value: str) -> str:
    """A public asset path (``/…``) or an absolute URL — the dummy's ``avatarUrl`` refinement."""
    if value.startswith("/"):
        return value
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        raise ValueError("Expected an absolute URL or a public asset path")
    return value


def _rooted_path(value: str) -> str:
    """A ``/``-prefixed public path — the dummy's ``z.string().startsWith("/")``."""
    if not value.startswith("/"):
        raise ValueError("Expected a path starting with '/'")
    return value


def _is_none(value: Any) -> bool:
    return value is None


#: An absolute ``http``/``https`` URL. A string on the wire, not a ``pydantic.HttpUrl``: the
#: frontend compares and renders these verbatim, and pydantic's URL type normalizes (it appends a
#: trailing slash to a bare host), which would silently change a served source URL.
HttpUrl = Annotated[str, AfterValidator(_http_url)]

#: An absolute URL or a ``/``-rooted public asset path (avatars, thumbnails).
AssetRef = Annotated[str, AfterValidator(_asset_path)]

#: A ``/``-rooted public path (logos, artifact thumbnails).
RootedPath = Annotated[str, AfterValidator(_rooted_path)]

#: The five research states the backend actually distinguishes (D0 ruling S11). ``fully_enriched``
#: and ``failed`` — the dummy's original two — do not exist in the M8D lifecycle.
ResearchStatus = Literal["not_started", "in_progress", "needs_review", "completed", "suspended"]

#: The fit band. Nullable everywhere it appears (D0 ruling R7): an unscored account has no band,
#: and guessing "Medium" is a fabrication.
AccountFit = Literal["High", "Medium", "Low"]

#: An unknown optional value: absent from the JSON rather than ``null`` (see rule 2 above).
_Absent = Field(default=None, exclude_if=_is_none)


class V1Model(BaseModel):
    """Frozen, camelCase-on-the-wire, snake_case in Python — the frontend's JSON convention.

    Same configuration as ``accounts_list.WireModel`` plus ``serialize_by_alias``, so a plain
    ``model_dump()`` already produces the wire form and no serving path can forget ``by_alias``.
    ``extra="forbid"`` is what makes this a *contract*: a field the frontend does not know about
    cannot be smuggled onto the wire by a composition change.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


# --- account chrome ---------------------------------------------------------------------------


class AccountProject(V1Model):
    """One project that targets this account. ``name`` is the project row's own name."""

    id: str
    name: str


class AccountOwner(V1Model):
    """A workspace user. CRM data, never agent-written (master plan §6, ruling R6)."""

    id: str
    name: str
    avatar_url: AssetRef | None = _Absent


class AccountSocial(V1Model):
    """One social profile link on the account."""

    id: str
    label: Literal["LinkedIn", "Twitter", "Facebook", "Instagram"]
    url: HttpUrl


class AccountCustomField(V1Model):
    """A registry custom variable whose value is a claim; ``presentation`` from the registry row."""

    id: str
    label: str
    value: str
    presentation: Literal["text", "badge", "score"] = "text"
    primary: bool = False
    claim_id: str | None = None


# --- the research display layer ---------------------------------------------------------------


class SellerPassage(V1Model):
    document_id: str
    sha256: str
    quote: str
    start: int
    end: int


class ResearchEvidence(V1Model):
    """One row per claim cited on the page — the hover card behind a citation chip.

    ``quote`` is the verbatim evidence span, or ``null`` with ``research_excerpt`` carrying the
    research sentence when no original-source quote exists; a quotation is never fabricated.
    ``source_url`` is ``null`` for private records (``verification_kind="record"``: email checks,
    database rows). ``verified_at`` is the claim's ``observed_at``; ``published_at`` the source's
    own date when known. The frontend resolves favicons by domain through its own proxy route, so
    ``favicon_url`` may be ``null`` even when the domain is known.
    """

    claim_id: str
    source_kind: (
        Literal["primary_quote", "source_excerpt", "provider_record", "inference"] | None
    ) = None
    source_excerpt: str | None = None
    qualifications: tuple[str, ...] = ()
    supporting_claim_ids: tuple[str, ...] = ()
    seller_passages: tuple[SellerPassage, ...] = ()
    research_field_key: str | None = _Absent
    source_url: HttpUrl | None
    source_domain: str | None
    favicon_url: HttpUrl | None
    title: str | None
    quote: str | None
    research_excerpt: str | None = _Absent
    published_at: str | None
    verified_at: str
    verification_kind: Literal["verified", "record"] = "verified"
    media_timestamp: str | None
    provider: str | None
    outreach_safe: bool


class ResearchInlineSegment(V1Model):
    """A clause of a sentence with the claim ids supporting *that clause*.

    Chips render after the clause, not the sentence — which is why the segment split is served
    rather than derived in the browser.
    """

    text: str
    claim_ids: tuple[str, ...] = ()


class ResearchSentence(V1Model):
    """One sentence of generated prose, carrying its sentence-level and clause-level citations."""

    text: str
    claim_ids: tuple[str, ...] = ()
    segments: tuple[ResearchInlineSegment, ...] | None = _Absent

    kind: Literal["fact", "inference", "quote", "qualified", "gap"] | None = None
    qualifications: tuple[str, ...] = ()


class ResearchContactReference(V1Model):
    """A contact named inside a display item — a chip that links to the contact page."""

    account_id: str
    contact_id: str
    name: str
    title: str | None = _Absent
    persona: str | None = _Absent
    email_state: Literal["verified", "unverified", "not_requested"] | None = _Absent
    avatar_url: AssetRef | None = _Absent


class ResearchSendLine(V1Model):
    """The contact page's suggested opener. A separate field, never inside quotation marks."""

    channel: str
    text: str
    claim_ids: tuple[str, ...] = ()


class ResearchItem(V1Model):
    """One evidence-backed item inside a section.

    ``priority`` is the best (lowest) ``signal_priority`` among the item's cited claims; the
    backend sorts P1 first (ruling R3). ``new_since_last_visit`` is served ``False`` — the
    frontend computes it from ``ResearchEvidence.verified_at`` against a locally stored last-visit
    stamp (decision D5), and no visit row exists server-side.
    """

    id: str
    h2: str
    body: tuple[ResearchSentence, ...]
    send_line: ResearchSendLine | None = None
    contact_refs: tuple[ResearchContactReference, ...] = ()
    inline_lead: bool | None = _Absent
    fit_disposition: Literal["support", "caveat"] | None = _Absent
    subject: ResearchContactReference | None = _Absent
    priority: Literal[1, 2, 3]
    new_since_last_visit: bool = False


class ResearchSection(V1Model):
    """One H1 section of a page.

    ``h1`` is the section's served vocabulary **without counts or parentheticals** — counts are
    ``len(items)`` (ruling R9). ``empty`` is true when the recipe matched nothing and the display
    model was never called; ``empty_message`` is optional server text, else the client prints its
    own. ``restricted`` marks the only sections that may carry ``outreach_safe=False`` claims
    (``do-not-mention`` / ``context-only`` / ``watch-outs``); the frontend shows them under an
    "Internal notes" control (ruling R2). ``pending`` is true only when the section will be
    written (its recipe matched claims and its page task is offered); a section that matches
    nothing is never pending.
    """

    key: str
    h1: str
    empty: bool
    items: tuple[ResearchItem, ...]
    intro: tuple[ResearchSentence, ...] | None = _Absent
    restricted: bool = False
    default_open: bool = False
    # Plan 2026-09-21: the section is missing AND a fleet task is writing it. Served with the one
    # ``empty_message`` sentence; the client polls the page while any section is pending.
    pending: bool = False
    empty_message: str | None = _Absent
    gaps: tuple[str, ...] = ()


class ResearchContextChoice(V1Model):
    project_id: str
    project_name: str
    context_id: str
    account_id: str


class ResearchQuality(V1Model):
    project_id: str | None = None
    context_id: str | None = None
    generation_id: str | None = None
    quality_state: Literal[
        "researching",
        "provisional",
        "reconciled",
        "partial",
        "needs_review",
        "suspended",
        "privacy_stopped",
        "context_required",
        "legacy",
    ]
    refresh_pending: bool = False
    gaps: tuple[str, ...] = ()
    contexts: tuple[ResearchContextChoice, ...] = ()


class ResearchDisplayBlock(V1Model):
    """A whole page's generated display: ``overview``, ``insights``, or ``contact``."""

    page: Literal["insights", "overview", "contact"]
    sections: tuple[ResearchSection, ...]
    research_quality: ResearchQuality | None = None


class BuyingCommitteeMember(V1Model):
    """One resolved committee member on the account detail.

    ``email`` and ``email_claim_id`` come from the ``core.work_email`` claim together — the claim
    id is how the frontend finds the evidence (ruling R5), replacing its old substring match on
    evidence text. ``linkedin_url`` is nullable (D3 ruling): a member resolved from a coverage row
    may have no LinkedIn URL, and the dummy renders the link only when present.
    """

    contact_id: str
    name: str
    title: str
    persona: str
    email: str | None
    email_claim_id: str | None
    linkedin_url: HttpUrl | None
    why_they_matter: str
    membership_state: Literal["candidate", "supported", "needs_verification", "excluded"] | None = (
        None
    )
    outreach_eligible: bool = False
    membership_gaps: tuple[str, ...] = ()


# --- account detail parts ---------------------------------------------------------------------


class AccountContact(V1Model):
    """A contact chip on the account detail. ``has_detail`` gates the link to the contact page."""

    id: str
    name: str
    avatar_url: AssetRef | None = _Absent
    title: str | None = _Absent
    persona: str | None = _Absent
    email_verified: bool | None = _Absent
    has_detail: bool = False


class AccountFitCriterion(V1Model):
    """A legacy fit-criteria row. May be empty in v1; ``fitCriteria`` predates the display layer."""

    id: str
    matched: bool
    title: str
    evidence: str


class AccountInsight(V1Model):
    """A source row in the account detail's insights list."""

    id: str
    source: Literal["link", "linkedin", "x"]
    title: str
    date_label: str
    url: HttpUrl


class ClueActor(V1Model):
    """An agent-performed action."""

    type: Literal["clue"]


class PersonActor(V1Model):
    """A user-performed action — the ``AccountOwner`` shape plus its discriminator."""

    type: Literal["person"]
    id: str
    name: str
    avatar_url: AssetRef | None = _Absent


class AccountActivity(V1Model):
    """One durable activity row (account detail and workspace payload; never the list row).

    An unattributed event carries no ``actor`` at all rather than a fabricated one. ``is_sample``
    exists only for fixtures.
    """

    id: str
    kind: Literal["contacts", "summary", "created", "artifact", "updated"]
    text: str
    time_label: str
    actor: ClueActor | PersonActor | None = Field(
        default=None, discriminator="type", exclude_if=_is_none
    )
    action: str | None = _Absent
    occurred_at: str | None = _Absent
    is_sample: bool | None = _Absent


# --- workspace parts --------------------------------------------------------------------------


class WorkspaceInsight(V1Model):
    """A source row on the workspace/insights tab, with its served summary line."""

    id: str
    source: Literal["link", "linkedin", "x"]
    title: str
    source_label: str
    url: HttpUrl
    summary: str


class AccountArtifact(V1Model):
    """A generated artifact bound to this account. ``updated_at`` from the artifact record only."""

    id: str
    title: str
    type: Literal["presentation", "document", "web", "ad", "email"]
    account_id: str | None = _Absent
    project_name: str | None = _Absent
    updated_at: str | None = _Absent
    thumbnail_path: RootedPath
    last_edited_label: str


# --- contact parts ----------------------------------------------------------------------------


class ContactEvidence(V1Model):
    """A source row in the contact page's evidence list (distinct from ``ResearchEvidence``)."""

    id: str
    source: Literal["link", "linkedin", "x"]
    title: str
    date_label: str
    url: HttpUrl


# --- E1: the accounts list row ----------------------------------------------------------------


class AccountV1(V1Model):
    """``GET /frontend/v1/accounts`` — one row of the accounts table.

    ``logo_path`` is nullable. D0 ruling S2 ("no logo pipeline") was superseded 2026-09-11: an
    account with a ``core.logo_url`` mark serves the platform's logo route, and the frontend
    renders its building glyph on ``null``. ``website_url`` is nullable when the account has no
    ``primary_domain``. ``fit_score`` and ``overall_fit`` are ``null`` **together** when the
    account has not been scored — never ``0``, never a guessed band (ruling R7).
    """

    id: str
    name: str
    logo_path: AssetRef | None
    website_url: HttpUrl | None
    research_status: ResearchStatus
    research_status_label: str | None = _Absent
    research_is_refreshing: bool = False
    overall_fit: AccountFit | None
    fit_score: int | None
    revenue_band: str
    employee_band: str
    location_count: int
    locations_label: str | None = _Absent
    owner: AccountOwner | None = None
    created_by: AccountOwner | None = None
    industry_labels: tuple[str, ...] = ()
    socials: tuple[AccountSocial, ...] = ()
    created_at: str | None = _Absent
    last_modified_at: str | None = _Absent
    primary_project_id: str | None = None
    projects: tuple[AccountProject, ...] = ()
    custom_fields: tuple[AccountCustomField, ...] = ()


# --- E2: the account detail -------------------------------------------------------------------


class AccountDetailV1(V1Model):
    """``GET /frontend/v1/accounts/{id}`` — the account detail and preview.

    Not a superset of :class:`AccountV1`: the detail serves *labels* where the list serves bands
    (``headcount_label`` vs ``employee_band``), and it drops the list-only membership fields
    (``projects``, ``primary_project_id``, ``research_is_refreshing``, ``location_count``). The
    Zod schema is the arbiter of that split, and the parity test enforces it.

    ``created_at`` / ``last_modified_at`` are **required** here (they are optional on the list
    row), and ``fit_criteria`` / ``contacts`` / ``insights`` / ``activity`` are required lists —
    an empty list is the honest answer, an absent key is not.
    """

    id: str
    name: str
    preview_title: str
    logo_path: AssetRef | None
    website_url: HttpUrl | None
    website_label: str
    research_status: ResearchStatus
    research_status_label: str | None = _Absent
    owner: AccountOwner | None = None
    created_by: AccountOwner | None = None
    industry_labels: tuple[str, ...] = ()
    headcount_label: str
    locations_label: str
    revenue_label: str
    founded_label: str | None = _Absent
    funding_label: str | None = _Absent
    fit_score: int | None
    fit_score_label: str | None = _Absent
    created_at: str
    last_modified_at: str
    socials: tuple[AccountSocial, ...] = ()
    custom_fields: tuple[AccountCustomField, ...] = ()
    overall_fit: AccountFit | None
    summary_paragraphs: tuple[str, ...] = ()
    business_paragraphs: tuple[str, ...] = ()
    fit_criteria: tuple[AccountFitCriterion, ...]
    contacts: tuple[AccountContact, ...]
    insights: tuple[AccountInsight, ...]
    activity: tuple[AccountActivity, ...]
    header_metadata: tuple[str, ...] = ()
    research_evidence: tuple[ResearchEvidence, ...] = ()
    overview_display: ResearchDisplayBlock | None = _Absent
    buying_committee: tuple[BuyingCommitteeMember, ...] = ()


# --- E3: the account workspace ----------------------------------------------------------------


class AccountWorkspaceV1(V1Model):
    """``GET /frontend/v1/accounts/{id}/workspace`` — the insights and artifacts tabs.

    ``insight_summary`` is computed by the backend: ``"{n} insights"`` over items in
    non-restricted sections and ``"{m} people"`` over committee members. ``artifacts`` is ``[]``
    in v1 (D0 ruling S9) — account-scoped artifact binding is its own later slice.
    """

    account_id: str
    insights: tuple[WorkspaceInsight, ...]
    insight_summary: tuple[str, ...] = ()
    research_evidence: tuple[ResearchEvidence, ...] = ()
    insights_display: ResearchDisplayBlock | None = _Absent
    artifacts: tuple[AccountArtifact, ...]
    activity: tuple[AccountActivity, ...]


# --- E4: the contacts list row ----------------------------------------------------------------


class AccountContactSummaryV1(V1Model):
    """``GET /frontend/v1/accounts/{id}/contacts`` — one row of the contacts table.

    ``title`` is nullable (D0 ruling S7): when no title claim exists the row shows "—" rather
    than an invented title. ``influence`` falls back to the persona-derived default table when
    the committee claim does not carry it (ruling S8) — served, never derived in the browser.
    """

    id: str
    name: str
    title: str | None
    persona: str
    persona_tone: Literal["olive", "orange", "blue", "cyan", "green", "pink", "red"]
    influence: Literal["High", "Medium", "Low"] | None
    avatar_url: AssetRef | None = _Absent
    email_status: Literal["available", "lookup"]
    email_label: str | None = _Absent
    socials: tuple[Literal["linkedin", "x", "facebook", "instagram", "whatsapp"], ...]
    profile_action: Literal["none", "preview", "page"] = "none"

    # --- E5: the contact detail -------------------------------------------------------------------

    membership_state: Literal["candidate", "supported", "needs_verification", "excluded"] | None = (
        None
    )
    outreach_eligible: bool = False
    membership_gaps: tuple[str, ...] = ()


class AccountContactDetailV1(AccountContactSummaryV1):
    """``GET /frontend/v1/accounts/{id}/contacts/{contactId}`` — the contact page.

    ``last_modified_at`` is the *contact's own* latest ``verified_at``, not the account's
    (ruling R8) — the dummy showed the account's stamp on the contact header. ``tenure_label``
    is served for the same reason: the frontend must never compute tenure from the browser clock,
    and ``employment_started_at`` exists for sorting and date display. ``email_claim_id`` is how
    the email chip finds its evidence (ruling R5).
    """

    account_id: str
    account_name: str
    account_logo_path: AssetRef | None
    recent_signals_label: str
    linkedin_label: str
    linkedin_url: HttpUrl
    x_label: str | None = _Absent
    x_url: HttpUrl | None = _Absent
    email_verified_at: str | None = _Absent
    email_claim_id: str | None = None
    location_label: str | None = _Absent
    best_first_channel_label: str | None = _Absent
    education_label: str | None = _Absent
    tenure_label: str | None = _Absent
    employment_started_at: str | None = _Absent
    linkedin_followers: int | None = _Absent
    linkedin_creator: bool | None = _Absent
    location_claim_id: str | None = _Absent
    reports: tuple[ResearchContactReference, ...] = ()
    overview_paragraphs: tuple[str, ...] = ()
    evidence: tuple[ContactEvidence, ...]
    research_evidence: tuple[ResearchEvidence, ...] = ()
    custom_fields: tuple[AccountCustomField, ...] = ()
    contact_display: ResearchDisplayBlock | None = _Absent
    last_modified_at: str


# --- envelopes --------------------------------------------------------------------------------


class AccountsMeta(V1Model):
    """List pagination. ``total`` counts the whole filtered set, not the page."""

    total: int
    next_cursor: str | None


class AccountsResponseV1(V1Model):
    """``{data, meta}`` for E1."""

    data: tuple[AccountV1, ...]
    meta: AccountsMeta


class AccountDetailResponseV1(V1Model):
    """``{data}`` for E2."""

    data: AccountDetailV1


class AccountWorkspaceResponseV1(V1Model):
    """``{data}`` for E3."""

    data: AccountWorkspaceV1


class AccountContactsMeta(V1Model):
    """Contact-list metadata. The contacts list is not paginated in v1; ``total`` is the count."""

    total: int


class AccountContactsResponseV1(V1Model):
    """``{data, meta}`` for E4.

    The dummy's ``AccountContactsResponseSchema`` carries only ``data``; v1 adds ``meta.total`` so
    the screen's "N contacts" count is served rather than inferred from a page. An extra key on
    the envelope is additive for the frontend — its Zod object is not strict — and the parity test
    covers the *payload* schemas, which are unchanged.
    """

    data: tuple[AccountContactSummaryV1, ...]
    meta: AccountContactsMeta


class AccountContactDetailResponseV1(V1Model):
    """``{data}`` for E5."""

    data: AccountContactDetailV1


#: The five payload models, keyed by the Zod schema they must match field-for-field. This mapping
#: is what ``tests/api/contract_v1/test_contract_v1.py`` iterates; adding a payload to contract v1
#: means adding it here, vendoring its Zod, and documenting its field table.
V1_PAYLOADS: dict[str, type[BaseModel]] = {
    "AccountSchema": AccountV1,
    "AccountDetailSchema": AccountDetailV1,
    "AccountWorkspaceSchema": AccountWorkspaceV1,
    "AccountContactSummarySchema": AccountContactSummaryV1,
    "AccountContactDetailSchema": AccountContactDetailV1,
}
