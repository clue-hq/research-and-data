"""Field keys and the field definition contract (M0.2).

Two things live here, both from substrate §1/§3 and conventions §3:

* **Field keys are an open registry, not an enum.** A ``field_key`` is a namespaced,
  lowercase, dotted identifier (``core.employee_count``, ``account.resonance.culture``,
  ``contact.facet.recent_post``, ``healthcare.npi``). New fields and whole verticals are
  *registered* (rows / pack registration), never added by forking a Python enum — that is
  the generalization the prototype could not make. We validate *well-formedness* and
  *classify* into a field-class; we do not enumerate the values.
* **``FieldDef``** mirrors the ``field_definition`` contract: the per-field declaration of
  type, validation, ordered tier plan, freshness TTL, scoring/deep pass, and gate. M3
  compiles ICPs into these; M0.2 only defines the shape.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import timedelta
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, JsonValue

from clue_core.enums import PassKind, ResearchScope, ReuseScope

# --- canonical field-key namespaces (conventions §3) -----------------------
NS_CORE = "core"  # commodity facts: employee_count, primary_domain, work_email...
NS_ACCOUNT = "account"  # account facts: recent_funding, hiring_velocity_eng...
NS_ACCOUNT_RESONANCE = "account.resonance"  # culture/sentiment/frustrations (Doc C §2)
NS_CONTACT = "contact"  # contact facts: role_on_committee, persona...
NS_CONTACT_FACET = "contact.facet"  # rich personal hooks (Doc C §2; governed by M10)


class FieldClass(StrEnum):
    """The class a field-key belongs to. Resonance/facet are first-class so the deep,
    governed field-classes are addressable without enumerating their members."""

    CORE = "core"
    ACCOUNT = "account"
    ACCOUNT_RESONANCE = "account.resonance"
    CONTACT = "contact"
    CONTACT_FACET = "contact.facet"
    PACK = "pack"  # a vertical pack namespace, e.g. healthcare.* / frontier_ai.*


# The account research axis owns organization-level facts only.  Keep this boundary next to the
# canonical field classifier so provider acquisition, agent planning, and handoff assembly cannot
# drift into treating contact/contact-facet fields as account work merely because one ICP/directive
# activates both axes.
ACCOUNT_AXIS_FIELD_CLASSES = frozenset(
    {FieldClass.CORE, FieldClass.ACCOUNT, FieldClass.ACCOUNT_RESONANCE, FieldClass.PACK}
)


# Longest-prefix first so "account.resonance" wins over "account".
_CANONICAL_PREFIXES: tuple[tuple[str, FieldClass], ...] = (
    (NS_ACCOUNT_RESONANCE, FieldClass.ACCOUNT_RESONANCE),
    (NS_CONTACT_FACET, FieldClass.CONTACT_FACET),
    (NS_CORE, FieldClass.CORE),
    (NS_ACCOUNT, FieldClass.ACCOUNT),
    (NS_CONTACT, FieldClass.CONTACT),
)

# namespace.name with >=2 lowercase identifier segments.
_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")

# Registered vertical packs (open by registration — M3.3 fills this).
_REGISTERED_PACKS: set[str] = set()


def is_valid_field_key(key: str) -> bool:
    """True if ``key`` is a well-formed namespaced field key."""
    return bool(_FIELD_KEY_RE.fullmatch(key))


def is_field_key_or_class(token: str) -> bool:
    """True if ``token`` is a field key OR a bare field-class / pack namespace.

    A ``source_manifest`` ``yields`` entry may be a full field key (``account.recent_funding``)
    *or* a field-class it can populate — including a single-segment class/pack namespace
    (``core``, ``account``, ``healthcare``), which is not a valid field *key* (those need >=2
    segments) but is a valid *class*. Used to validate :class:`SourceManifest.yields`.
    """
    return is_valid_field_key(token) or bool(re.fullmatch(r"[a-z][a-z0-9_]*", token))


def _ensure_field_key(key: str) -> str:
    if not is_valid_field_key(key):
        raise ValueError(
            f"invalid field_key {key!r}: expected a lowercase, dotted, namespaced "
            "identifier such as 'account.recent_funding' or 'contact.facet.recent_post'"
        )
    return key


def classify_field_key(key: str) -> FieldClass:
    """Classify a (well-formed) field key into its :class:`FieldClass`."""
    _ensure_field_key(key)
    for prefix, field_class in _CANONICAL_PREFIXES:
        if key == prefix or key.startswith(prefix + "."):
            return field_class
    return FieldClass.PACK


def account_axis_field_keys(keys: Sequence[str]) -> tuple[str, ...]:
    """Return the stable, de-duplicated account-axis subset of ``keys``.

    A confirmed deep-research directive intentionally carries both account and contact fields.
    Account-only provider calls and account-agent plans must project that shared authority onto the
    account axis; contact fields remain available to the later committee/contact fleet.
    """

    return tuple(
        dict.fromkeys(key for key in keys if classify_field_key(key) in ACCOUNT_AXIS_FIELD_CLASSES)
    )


def field_namespace(key: str) -> str:
    """Return the namespace of a field key (a canonical prefix, or the pack's first segment)."""
    _ensure_field_key(key)
    for prefix, _ in _CANONICAL_PREFIXES:
        if key == prefix or key.startswith(prefix + "."):
            return prefix
    return key.split(".", 1)[0]


def field_key(namespace: str, *parts: str) -> str:
    """Build and validate a field key from a namespace and leaf parts."""
    return _ensure_field_key(".".join((namespace, *parts)))


def register_pack(pack: str) -> None:
    """Register a vertical pack namespace (e.g. ``"healthcare"``). M3.3 owns pack content;
    this records the namespace so tooling can distinguish a known pack from a typo."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", pack):
        raise ValueError(f"invalid pack namespace {pack!r}")
    _REGISTERED_PACKS.add(pack)


def is_pack_registered(pack: str) -> bool:
    return pack in _REGISTERED_PACKS


# A validated field-key string. Statically a ``str``; rejects malformed keys at validation.
FieldKey = Annotated[str, AfterValidator(_ensure_field_key)]


class FieldDef(BaseModel):
    """``field_definition`` (substrate §1/§3): the per-field contract.

    The field registry — a table of these — IS the contract that makes fields and
    verticals pluggable by registration. M3 compiles ICPs into ``FieldDef`` rows; the
    source layer (M4) reads ``tier_plan``; verification (M9) reads ``freshness_ttl``/``gate``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    value_type: str  # declared value shape, e.g. "int" | "str" | "enum:...". (contract: `type`)
    validation: dict[str, JsonValue] | None = None
    tier_plan: tuple[str, ...] = ()  # ordered resolver/source keys (1->...->4)
    freshness_ttl: timedelta | None = None
    pass_kind: PassKind  # (contract: `pass`) scoring vs deep
    gate: str | None = None  # gate expression, e.g. "tier>=1" | "committee-gated"
    # The two-tier signal model (Doc C §1): fields sharing a `signal_class` are the cheap `scoring`
    # proxy and the `deep` narrative of one signal — the research-schema compiler (M3.2) links them.
    # An extension of the field_definition contract (registered, optional); the merge/source layers
    # ignore it.
    signal_class: str | None = None
    # Cross-tenant reuse class *declared at the field* (M2.5 / ENG-165 W1). The declaration is the
    # source of truth for whether claims of this field amortize across clients (`public_footprint`)
    # or are tenant-isolated (`tenant_private`); ``None`` means "fall back to the class default"
    # (:func:`default_reuse_scope`) — except a ``PACK`` field, which has no safe default and so MUST
    # declare one (the classifier consults this before the prefix heuristic; the write boundary is
    # fail-closed on it). An additive extension of the field_definition contract (conventions §4).
    reuse_scope: ReuseScope | None = None
    # Field **species** declared at the field (contract-delta 2026-08-08, FI-2 slice 0 — mirrors
    # ``reuse_scope`` exactly). ``None`` means "fall back to the ratified default"
    # (:func:`default_research_scope`); a ``<pack>.*`` field must declare one — fail-loud at pack
    # authoring, at field-proposal validation, and at registration alike (``client.*`` excepted —
    # it is neutral by construction and workspace-scoped). Drives
    # economics (may a fresh claim from another project be reused?) and project-lens membership,
    # never privacy — that stays ``reuse_scope``'s job. An additive extension of the
    # field_definition contract (conventions §4).
    research_scope: ResearchScope | None = None

    @property
    def field_class(self) -> FieldClass:
        return classify_field_key(self.field_key)


# --- cross-tenant reuse classification (M2.5 / ENG-165 W2) ------------------
# The canonical default reuse class per field-class, kept in ``core`` so both the M2 classifier
# (``identity.classify_reuse_scope``) and the M3 pack/field authoring read one shared definition
# without importing each other (the import-linter independence contract). The *declared* scope on a
# ``FieldDef`` (W1) always overrides this default; the default only fills the gap for an undeclared
# field — and there is deliberately **no safe default for a ``PACK`` field** (returns ``None``), so
# a vertical pack must declare the scope of every ``<pack>.*`` field (closing the "<pack>.* silently
# defaults public" gap; substrate §2).
_PRIVATE_BY_DEFAULT: frozenset[FieldClass] = frozenset(
    {FieldClass.CONTACT, FieldClass.CONTACT_FACET, FieldClass.ACCOUNT_RESONANCE}
)
_PUBLIC_BY_DEFAULT: frozenset[FieldClass] = frozenset({FieldClass.CORE, FieldClass.ACCOUNT})


def default_reuse_scope(field_class: FieldClass) -> ReuseScope | None:
    """The default cross-tenant :class:`ReuseScope` for a field-class (M2.5 / ENG-165 W2).

    ``CORE`` / ``ACCOUNT`` firmographic-technographic facts amortize across clients
    (``PUBLIC_FOOTPRINT``); ``CONTACT`` / ``CONTACT_FACET`` personal data and ``ACCOUNT_RESONANCE``
    client-shaped consumption are ``TENANT_PRIVATE``. A ``PACK`` field has **no safe default** and
    returns ``None`` — it must declare its own ``reuse_scope`` (fail-closed). The per-field declared
    scope (``FieldDef.reuse_scope``) overrides this (see :func:`resolve_reuse_scope`).
    """
    if field_class in _PRIVATE_BY_DEFAULT:
        return ReuseScope.TENANT_PRIVATE
    if field_class in _PUBLIC_BY_DEFAULT:
        return ReuseScope.PUBLIC_FOOTPRINT
    return None  # PACK — no safe default; the field must declare its scope


def resolve_reuse_scope(field: FieldDef) -> ReuseScope | None:
    """The effective reuse scope of a field: its **declared** scope if set, else the class default.

    Returns ``None`` only for an *undeclared* ``PACK`` field (no safe default) — callers treat that
    as fail-closed (authoring rejects it; the claim-write boundary refuses to write it). The single
    place "what scope does this field's claims get" is decided, so the classifier, the compiler's
    plan partitions, and the write guard never re-derive it differently.
    """
    return (
        field.reuse_scope
        if field.reuse_scope is not None
        else default_reuse_scope(field.field_class)
    )


# --- field species (FI-2 P3; contract-delta 2026-08-08) ---------------------
# The founder-ratified species table (FI-2 spec §5.2) as data, kept in ``core`` so the registry,
# the account/contact research economics, and the two-lens read layer all read one definition
# without importing each other. Everything not named here is a world-fact about the account or
# contact and is therefore ``PROJECT_NEUTRAL`` — including ``account.operational_pain`` /
# ``.strategic_moves`` and ``account.resonance.*`` (ratified neutral: the *facts* are account
# truth; the campaign-relative angle lives in the value narrative).
_PROJECT_RELATIVE_PREFIXES: tuple[str, ...] = ("account.scoring.",)  # fit / intent / tier + kin
_PROJECT_RELATIVE_KEYS: frozenset[str] = frozenset(
    {
        "account.value_narrative",  # the per-persona argument: product + ICP + campaign flavored
        "contact.persona",  # the buying committee is a per-project targeting decision
        "contact.role_on_committee",
    }
)


def default_research_scope(field_class: FieldClass, field_key: str) -> ResearchScope:
    """The default :class:`ResearchScope` (species) of a field (FI-2 §5.2).

    ``PROJECT_RELATIVE`` for the ratified relative families — ``account.scoring.*``,
    ``account.value_narrative``, ``contact.persona``, ``contact.role_on_committee``; every other
    field is ``PROJECT_NEUTRAL``, the safe species (a neutral read is a superset read; the
    economics consequence of a wrong neutral is a skipped re-spend, never a leaked or
    mis-attributed claim). A ``<pack>.*`` field has no *authored* default — pack authoring and the
    registry both refuse one that declares nothing (``client.*`` excepted) — so the neutral answer
    here only ever serves ``client.*`` and legacy rows. The per-field declaration
    (``FieldDef.research_scope``) overrides this (see :func:`resolve_research_scope`).

    The **field key alone decides**: this function *is* the ratified rule, so it cannot return a
    different species than §5.2 for a given key. ``field_class`` is accepted for symmetry with
    :func:`default_reuse_scope` (and so a caller that already classified the key can pass it), but
    it deliberately does not participate — a mismatched pair could otherwise silently downgrade a
    relative key to neutral.
    """
    del field_class  # documented above: the key is the rule; the class must not change the answer
    if field_key in _PROJECT_RELATIVE_KEYS or field_key.startswith(_PROJECT_RELATIVE_PREFIXES):
        return ResearchScope.PROJECT_RELATIVE
    return ResearchScope.PROJECT_NEUTRAL


def resolve_research_scope(field: FieldDef) -> ResearchScope:
    """The effective species of a field: its **declared** scope if set, else the ratified default.

    The single place "is this field's value project-relative?" is decided, so the read lens, the
    fresh-skip economics, and the supersede predicates never re-derive it differently.

    **Asymmetry with** :func:`resolve_reuse_scope`, deliberate: that one returns ``None`` for an
    undeclared ``PACK`` field and every caller fails closed, while this one always answers, folding
    an undeclared field into the safe ``PROJECT_NEUTRAL`` species. There is no fail-closed branch
    here because a field cannot *reach* this function undeclared once it is DB-resident: both
    registration gates — ``clue_research.claimstore.registry.register_field`` and the pack-catalog
    loader — reject a ``<pack>.*`` field that declares no ``research_scope`` (``client.*``
    excepted, and legacy rows predate the column). So the neutral answer only ever serves those two
    already-vetted cases, and neutral is the safe direction anyway: a wrong neutral costs a skipped
    re-spend, never a leaked or mis-attributed claim. Slice-3 economics callers therefore read this
    result directly and do **not** need an undeclared-field guard of their own.
    """
    return (
        field.research_scope
        if field.research_scope is not None
        else default_research_scope(field.field_class, field.field_key)
    )
