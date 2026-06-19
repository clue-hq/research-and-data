"""The research-schema compiler (M3.2 / ENG-109).

The milestone's core engine (substrate §3): a confirmed ICP spec compiles into a **field plan** — a
deterministic, ordered set of typed ``field_definition`` views, each carrying its ``tier_plan``,
``freshness_ttl``, ``gate`` and — critically — its ``pass{scoring|deep}`` tag, because this is where
the two-pass economics are *declared and auditable* (payoff 2). It is a **pure config transform**
that reads the ICP spec (M3.1), the M1.3 field registry, and the M3.3 pack field sets, emitting a
plan — no ``source_manifest`` / resolver / LLM dependency (those are M4). ``tier_plan`` is *named*
here and *implemented* in M4, so swapping a provider never re-compiles a plan (conventions §2).

The plan is computed on demand and deterministic: the registry rejects conflicting redefinitions
(M1.3), so a given ``field_key`` resolves to a stable definition — hence the same ICP-spec version
yields an identical plan (a ``plan_hash`` makes it content-addressable). M6 reads ``scoring_fields``
(Pass A, all accounts); M8 reads ``deep_fields`` (Pass B, high tier only); M4 executes the
``tier_plan``s. They never re-derive "which fields, which tiers, which pass".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import get_field
from clue_research.core import FieldDef, ICPSpec, PassKind
from clue_research.icp.catalog import UnknownPackError, get_pack_field_set
from clue_research.icp.spec import UnknownICPSpecError, get_active_icp


class CompileError(ValueError):
    """Raised when an ICP spec cannot compile to a complete plan. Carries every ``diagnostic`` (a
    field-key missing from the registry, an unknown pack, an override targeting a non-active field);
    no partial/ambiguous plan is ever emitted (empty-or-correct discipline applied to config)."""

    def __init__(
        self, client_id: str, icp_key: str, version: int, diagnostics: tuple[str, ...]
    ) -> None:
        self.diagnostics = diagnostics
        joined = "; ".join(diagnostics)
        super().__init__(
            f"cannot compile ICP spec ({client_id!r}, {icp_key!r}, v{version}): {joined}"
        )


class FieldOverride(BaseModel):
    """A per-ICP override of a field's source-execution knobs (precedence: override > registry
    default). Only set values override; ``None`` leaves the registry value. The compiler applies
    these; their persistence (an ICP-spec slot) is M5's concern — kept a parameter here for now."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tier_plan: tuple[str, ...] | None = None
    gate: str | None = None
    freshness_ttl: timedelta | None = None


class FieldPlanEntry(BaseModel):
    """One field in the plan: its materialized ``field_definition`` view + why it is in the plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: FieldDef
    contributed_by: tuple[str, ...] = ()  # "icp" and/or "pack:<pack_key>" (explainability)


class SignalClassLink(BaseModel):
    """A two-tier signal class (Doc C §1): the ``scoring`` proxy field-keys and ``deep`` narrative
    field-keys that belong to one signal, so Pass A and Pass B stay coherent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_class: str
    scoring: tuple[str, ...] = ()
    deep: tuple[str, ...] = ()


class FieldPlan(BaseModel):
    """The compiled research schema for one ICP-spec version — the single contract M4/M6/M8 consume.

    ``fields`` is the full ordered plan; ``scoring_fields`` / ``deep_fields`` are the first-class
    two-pass subsets (the auditable statement of what runs on whom); ``signal_classes`` records the
    proxy↔narrative links; ``plan_hash`` content-addresses it (stable per ICP-spec version).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_id: str
    icp_key: str
    icp_version: int
    fields: tuple[FieldPlanEntry, ...] = ()
    scoring_fields: tuple[FieldPlanEntry, ...] = ()
    deep_fields: tuple[FieldPlanEntry, ...] = ()
    signal_classes: tuple[SignalClassLink, ...] = ()
    plan_hash: str = ""


def _apply_override(field: FieldDef, override: FieldOverride) -> FieldDef:
    update: dict[str, Any] = {}
    if override.tier_plan is not None:
        update["tier_plan"] = override.tier_plan
    if override.gate is not None:
        update["gate"] = override.gate
    if override.freshness_ttl is not None:
        update["freshness_ttl"] = override.freshness_ttl
    return field.model_copy(update=update) if update else field


def _build_signal_links(entries: tuple[FieldPlanEntry, ...]) -> tuple[SignalClassLink, ...]:
    groups: dict[str, dict[str, list[str]]] = {}
    for entry in entries:
        signal_class = entry.field.signal_class
        if signal_class is None:
            continue
        group = groups.setdefault(signal_class, {"scoring": [], "deep": []})
        bucket = "scoring" if entry.field.pass_kind is PassKind.SCORING else "deep"
        group[bucket].append(entry.field.field_key)
    return tuple(
        SignalClassLink(
            signal_class=signal_class,
            scoring=tuple(group["scoring"]),
            deep=tuple(group["deep"]),
        )
        for signal_class, group in sorted(groups.items())
    )


def _plan_hash(
    client_id: str, icp_key: str, icp_version: int, entries: tuple[FieldPlanEntry, ...]
) -> str:
    payload = {
        "client_id": client_id,
        "icp_key": icp_key,
        "icp_version": icp_version,
        "fields": [
            {
                "field_key": e.field.field_key,
                "value_type": e.field.value_type,
                "validation": e.field.validation,
                "tier_plan": list(e.field.tier_plan),
                "freshness_ttl": (
                    e.field.freshness_ttl.total_seconds()
                    if e.field.freshness_ttl is not None
                    else None
                ),
                "gate": e.field.gate,
                "pass": e.field.pass_kind.value,
                "signal_class": e.field.signal_class,
            }
            for e in entries
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


async def compile_field_plan(
    conn: AsyncConnection,
    icp_spec: ICPSpec,
    *,
    overrides: Mapping[str, FieldOverride] | None = None,
) -> FieldPlan:
    """Compile an ICP spec into a typed :class:`FieldPlan`.

    Resolves the active field set = ``icp_spec.field_keys`` ∪ each enabled pack's field set (M3.3),
    de-duplicated in first-seen order; materializes each field's registry ``field_definition``;
    applies any per-ICP ``overrides`` (override > registry default); partitions ``scoring`` vs
    ``deep``; links signal classes. Any field-key missing from the registry, unknown pack, or
    override targeting a non-active field makes ``compile`` raise :class:`CompileError` with every
    diagnostic — never a partial plan. Deterministic: same inputs → identical plan + ``plan_hash``.
    """
    override_map = dict(overrides or {})
    diagnostics: list[str] = []
    ordered_keys: list[str] = []
    seen: set[str] = set()
    contributed: dict[str, list[str]] = {}

    def _add(field_key: str, origin: str) -> None:
        if field_key not in seen:
            seen.add(field_key)
            ordered_keys.append(field_key)
            contributed[field_key] = []
        if origin not in contributed[field_key]:
            contributed[field_key].append(origin)

    for field_key in icp_spec.field_keys:
        _add(field_key, "icp")
    for pack_key in icp_spec.enabled_packs:
        try:
            pack_fields = await get_pack_field_set(conn, pack_key)
        except UnknownPackError:
            diagnostics.append(f"enabled pack {pack_key!r} is not in the M3.3 catalog")
            continue
        for pack_field in pack_fields:
            _add(pack_field.field_key, f"pack:{pack_key}")

    entries: list[FieldPlanEntry] = []
    for field_key in ordered_keys:
        field_def = await get_field(conn, field_key)
        if field_def is None:
            diagnostics.append(
                f"field_key {field_key!r} is not registered in the field registry (M1.3)"
            )
            continue
        override = override_map.get(field_key)
        if override is not None:
            field_def = _apply_override(field_def, override)
        entries.append(
            FieldPlanEntry(field=field_def, contributed_by=tuple(contributed[field_key]))
        )

    for override_key in override_map:
        if override_key not in seen:
            diagnostics.append(
                f"override targets field_key {override_key!r} not in the active field set"
            )

    if diagnostics:
        raise CompileError(
            icp_spec.client_id, icp_spec.icp_key, icp_spec.version, tuple(diagnostics)
        )

    frozen_entries = tuple(entries)
    return FieldPlan(
        client_id=icp_spec.client_id,
        icp_key=icp_spec.icp_key,
        icp_version=icp_spec.version,
        fields=frozen_entries,
        scoring_fields=tuple(e for e in frozen_entries if e.field.pass_kind is PassKind.SCORING),
        deep_fields=tuple(e for e in frozen_entries if e.field.pass_kind is PassKind.DEEP),
        signal_classes=_build_signal_links(frozen_entries),
        plan_hash=_plan_hash(
            icp_spec.client_id, icp_spec.icp_key, icp_spec.version, frozen_entries
        ),
    )


async def compile_active_icp(conn: AsyncConnection, client_id: str, icp_key: str) -> FieldPlan:
    """Convenience: compile the currently-active ICP spec for ``(client_id, icp_key)`` (what M6
    runs Pass A against). Raises :class:`UnknownICPSpecError` if no active spec exists."""
    spec = await get_active_icp(conn, client_id, icp_key)
    if spec is None:
        raise UnknownICPSpecError(f"no active ICP spec for ({client_id!r}, {icp_key!r})")
    return await compile_field_plan(conn, spec)


__all__ = [
    "FieldPlan",
    "FieldPlanEntry",
    "SignalClassLink",
    "FieldOverride",
    "CompileError",
    "compile_field_plan",
    "compile_active_icp",
]
