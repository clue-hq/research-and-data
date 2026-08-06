"""Provider-neutral, offline resolver over exact-contact grounded snapshot fields (M8C C4)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from clue_core import (
    Claim,
    Entity,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldClass,
    FieldDef,
    IdentityBinding,
    ResearchMode,
    UseClass,
    contact_claim,
    new_run_id,
    revalidate_with,
    serialize_value_json,
    to_value_json,
)
from clue_research.resolvers import SynthesizedField


class GroundedContactSnapshotResolver:
    """Expose already-paid, exact-bound contact fields through the shared ``Resolver`` seam.

    Acquisition code supplies provider-neutral ``SynthesizedField`` values and immutable lineage.
    This class performs no I/O and emits conservative placeholder governance.
    ``fill_contact_field`` remains the sole authority that classifies the claim against the current
    canonical contact/account and stamps the final binding/use class.
    """

    tier = 4
    materialization_only = True

    def __init__(
        self,
        *,
        contact_entity_id: EntityId,
        fields: Sequence[SynthesizedField],
    ) -> None:
        self._contact_entity_id = contact_entity_id
        grouped: dict[str, list[SynthesizedField]] = {}
        for field in fields:
            grouped.setdefault(str(field.field_key), []).append(field)
        self._fields = {key: tuple(values) for key, values in grouped.items()}

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        if (
            entity.entity_type is not EntityType.CONTACT
            or entity.entity_id != self._contact_entity_id
            or field.field_class is not FieldClass.CONTACT_FACET
        ):
            return []

        claims: list[Claim] = []
        seen: set[str] = set()
        for candidate in self._fields.get(str(field.field_key), ()):
            if (
                candidate.field_key != field.field_key
                or candidate.evidence_span not in candidate.retrieved_text
                or candidate.artifact_key is None
                or candidate.source_operation_ref is None
                or candidate.source_snapshot_ref is None
                or candidate.source_request_ref is None
            ):
                continue
            value = to_value_json(candidate.value)
            fingerprint = serialize_value_json(value)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            claim = contact_claim(
                entity_id=entity.entity_id,
                field_key=field.field_key,
                value_json=value,
                source_tier=4,
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                confidence=candidate.confidence,
                run_id=new_run_id(),
                research_mode=ResearchMode.CONTACT_PROFILING,
                identity_binding=IdentityBinding.WEAK,
                use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
                source_url=candidate.source_url,
                evidence_span=candidate.evidence_span,
                cost_cents=Decimal(0),
            )
            claims.append(
                revalidate_with(
                    claim,
                    artifact_key=candidate.artifact_key,
                    source_operation_ref=candidate.source_operation_ref,
                    source_snapshot_ref=candidate.source_snapshot_ref,
                    source_request_ref=candidate.source_request_ref,
                )
            )
        return claims


__all__ = ["GroundedContactSnapshotResolver"]
