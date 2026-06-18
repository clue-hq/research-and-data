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
from datetime import timedelta
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, JsonValue

from clue_research.core.enums import PassKind

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

    @property
    def field_class(self) -> FieldClass:
        return classify_field_key(self.field_key)
