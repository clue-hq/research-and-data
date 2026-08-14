"""S4-A exact-version, retention-safe Client-KB reader primitives.

The claim table's ``superseded_by`` column is a global lineage edge, not Client-KB version
membership. A claim selected by version ``vN`` remains a member of ``vN`` when a later version
``vN+1`` supersedes it. Membership is therefore determined exclusively by the version-marker/run
graph in :func:`read_client_kb_claims`; row-level supersession is used only when that graph selects
a different claim for the pinned version.

Retention is separate and remains fail-closed. Historical membership is read with
``include_superseded=True`` but ``include_expired=False``, so a prior version stays usable without
reviving a claim whose retention horizon has elapsed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.client_context_binding import get_workspace_client_binding
from clue_core import Claim, ClaimId, EntityId
from clue_projections import ClientKnowledgeTopic, client_knowledge_topic
from clue_research.claimstore import (
    FieldFilters,
    FieldRegistryScope,
    ResolvedFieldDefinition,
    WorkspaceScope,
    claims_by_ids,
    claims_for,
    list_effective_fields,
)
from clue_research.identity import get_account
from clue_research.stage0 import CLIENT_BASELINE_FIELDS, CLIENT_KB_VERSION, read_client_kb_claims

CLIENT_KNOWLEDGE_READER_POLICY_VERSION = "client-knowledge-reader-v1"


def _marker_version(value: JsonValue) -> int | None:
    if not isinstance(value, dict):
        return None
    version = value.get("version")
    return version if isinstance(version, int) and version >= 1 else None


def _ordered_field_keys(claims: Mapping[str, Claim]) -> tuple[str, ...]:
    baseline = tuple(field for field in CLIENT_BASELINE_FIELDS if field in claims)
    extended = tuple(sorted(set(claims) - set(CLIENT_BASELINE_FIELDS)))
    return (*baseline, *extended)


@dataclass(frozen=True, slots=True)
class PinnedClientKnowledge:
    """One exact account-wide Client-KB version after scope and retention enforcement."""

    workspace_id: str
    client_entity_id: EntityId
    client_kb_version: int
    claims_by_field: Mapping[str, Claim]
    claims_by_id: Mapping[ClaimId, Claim]
    definitions: Mapping[str, ResolvedFieldDefinition]
    ordered_field_keys: tuple[str, ...]

    def claim(self, claim_id: ClaimId) -> Claim | None:
        """Resolve one exact member; non-members and retention-expired rows are both absent."""

        return self.claims_by_id.get(claim_id)


@dataclass(frozen=True, slots=True)
class PinnedClientKnowledgePage:
    """Stable field ordering plus one bounded selection window."""

    field_keys: tuple[str, ...]
    total_matching: int
    has_more: bool
    next_after_field_key: str | None


class ClientKnowledgePositionInvalid(ValueError):
    """A cursor position is not a member of the exact pinned ordering."""


async def load_pinned_client_knowledge(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    client_kb_version: int,
) -> PinnedClientKnowledge | None:
    """Load one canonical workspace/client/version or return no scope-visible result.

    ``None`` deliberately collapses unknown client, foreign client, missing canonical binding, and
    missing/wrong version. A caller may expose one indistinguishable scope refusal for all of them.
    """

    binding = await get_workspace_client_binding(conn, workspace_id=workspace_id)
    account = await get_account(conn, client_entity_id)
    if (
        binding is None
        or binding.client_entity_id != client_entity_id
        or account is None
        or account.workspace_id != workspace_id
    ):
        return None

    scope = WorkspaceScope.for_workspace(workspace_id)
    markers = await claims_for(
        conn,
        client_entity_id,
        CLIENT_KB_VERSION,
        include_superseded=True,
        scope=scope,
    )
    if not any(
        marker.product_id is None and _marker_version(marker.value_json) == client_kb_version
        for marker in markers
    ):
        return None

    selected = await read_client_kb_claims(
        conn,
        client_entity_id,
        workspace_id=workspace_id,
        version=client_kb_version,
        product_id=None,
    )
    retention_eligible = await claims_by_ids(
        conn,
        (claim.id for claim in selected.values()),
        scope=scope,
        include_superseded=True,
        include_expired=False,
    )
    eligible_by_field = {
        field_key: claim for field_key, claim in selected.items() if claim.id in retention_eligible
    }
    resolved = await list_effective_fields(
        conn,
        scope=FieldRegistryScope.for_workspace(workspace_id),
        filters=FieldFilters(pack="client", active=None),
        include_retired=True,
    )
    return PinnedClientKnowledge(
        workspace_id=workspace_id,
        client_entity_id=client_entity_id,
        client_kb_version=client_kb_version,
        claims_by_field=MappingProxyType(eligible_by_field),
        claims_by_id=MappingProxyType({claim.id: claim for claim in eligible_by_field.values()}),
        definitions=MappingProxyType({item.field_def.field_key: item for item in resolved}),
        ordered_field_keys=_ordered_field_keys(eligible_by_field),
    )


def select_client_knowledge_page(
    pinned: PinnedClientKnowledge,
    *,
    topic: ClientKnowledgeTopic | None,
    field_key: str | None,
    after_field_key: str | None,
    limit: int,
) -> PinnedClientKnowledgePage:
    """Select one deterministic page without fetching or mutating anything.

    The cursor position is evaluated against the whole pinned ordering, not merely the filtered
    subset. This lets the S1 card omission cursor resume immediately after its last included field.
    A stale or invented position is refused instead of silently restarting or returning an empty
    page that could be mistaken for complete traversal.
    """

    if limit < 1:
        raise ValueError("Client-KB page limit must be positive")
    if after_field_key is None:
        start = 0
    else:
        try:
            start = pinned.ordered_field_keys.index(after_field_key) + 1
        except ValueError as exc:
            raise ClientKnowledgePositionInvalid(
                "cursor position is absent from the pinned Client-KB version"
            ) from exc

    def included(candidate: str) -> bool:
        return (topic is None or client_knowledge_topic(candidate) is topic) and (
            field_key is None or candidate == field_key
        )

    matching = tuple(item for item in pinned.ordered_field_keys if included(item))
    candidates = tuple(item for item in pinned.ordered_field_keys[start:] if included(item))
    page = candidates[:limit]
    has_more = len(candidates) > len(page)
    return PinnedClientKnowledgePage(
        field_keys=page,
        total_matching=len(matching),
        has_more=has_more,
        next_after_field_key=page[-1] if has_more and page else None,
    )


__all__ = [
    "CLIENT_KNOWLEDGE_READER_POLICY_VERSION",
    "ClientKnowledgePositionInvalid",
    "PinnedClientKnowledge",
    "PinnedClientKnowledgePage",
    "load_pinned_client_knowledge",
    "select_client_knowledge_page",
]
