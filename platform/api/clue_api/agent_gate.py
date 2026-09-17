"""The durable ``agent_gate`` substrate: an immutable gate and its insert-once answer.

FI Lane D slice **D4**, charter §3-P5(a) under ratified **§6-D3**. A gate is the platform's durable
answer to "the agent asked the human for authority, and here is exactly what it asked for". Two
records and no third:

* :func:`insert_gate` writes what was presented — subject, revision, digest, the server-derived
  maximum spend, the addressee — and never touches it again (append-only trigger).
* :func:`insert_gate_answer` writes that it was answered, **once**: ``gate_id`` is that table's
  primary key, so the second answer is a database refusal rather than a policy somebody has to
  remember to check. There is no status column on either row; :func:`get_gate` derives ``answer``
  by outer-joining the second table, and "open" simply means it found none.

Why the module has no model-shaped import: the HTTP turn route reads and writes gates, and the
ratified §6-D1 rule (guarded by ``tests.api.test_lane_d2_http_gateway_isolation``) is that nothing
the route can reach may reach a gateway, a model provider, or the deepagent runtime. So the gate
*substrate* lives here — plain SQL and value objects — while the governed **tool** that opens a gate
lives in :mod:`clue_api.agent_gate_tools`, which the worker composes and the route never imports.

Money on a gate is a :class:`~decimal.Decimal` count of cents plus an ISO-4217 currency, and it is
compared **numerically** everywhere (``Decimal("1200") == Decimal("1200.0000")``). The canonical
*text* form used in digests and captured request bytes goes through :func:`money_text` so one amount
has exactly one spelling.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = [
    "DECISIONS",
    "DEFAULT_GATE_CURRENCY",
    "GATE_KINDS",
    "GATE_OBJECT_TYPE",
    "KIND_DIRECTIVE_CONFIRMATION",
    "KIND_ICP_CONFIRMATION",
    "KIND_PRODUCT_SELECTION",
    "KIND_PRODUCT_SET_SELECTION",
    "AgentGateAnswerRow",
    "AgentGateRow",
    "AgentGateSubjectBinding",
    "GateAlreadyAnswered",
    "directive_confirmation_gate_id",
    "product_selection_gate_id",
    "product_set_selection_gate_id",
    "gate_answer_for_turn",
    "get_gate",
    "icp_artifact_gate_id",
    "insert_gate",
    "insert_gate_answer",
    "money_text",
    "open_gates_for_thread",
    "redact_gate_snapshots_for_subject",
]

#: The ``DomainObjectRef.object_type`` flavour a finalization's ``open_gate_refs`` carries. The
#: existing vocabulary is an open ``StableId``, so the gate slots into it without a contract delta:
#: ``{object_type: "agent_gate", object_id: <gate_id>}`` points at the row below, which is exactly
#: what §3-P5(a) asked ``open_gate_refs`` to become ("nothing reads it back — your gate row becomes
#: what it points at").
GATE_OBJECT_TYPE = "agent_gate"

#: The one kind D4 builds. The others exist in the DB CHECK because §3-P5(a) names them; a gate
#: substrate whose second kind needs a migration was never generic.
KIND_DIRECTIVE_CONFIRMATION = "directive_confirmation"
KIND_ICP_CONFIRMATION = "icp_confirmation"
KIND_PRODUCT_SELECTION = "product_selection"
#: A project targets a SET of products (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.3, ruling P1), so its
#: gate names its choices in ``decision_payload["selected_option_refs"]`` rather than in the
#: single-valued ``selected_option_ref``; the answer trigger enforces membership per element.
KIND_PRODUCT_SET_SELECTION = "product_set_selection"
GATE_KINDS = (
    KIND_DIRECTIVE_CONFIRMATION,
    KIND_ICP_CONFIRMATION,
    KIND_PRODUCT_SELECTION,
    KIND_PRODUCT_SET_SELECTION,
    "plan_approval",
    "budget_approval",
)

#: What a human may answer. ``revised`` is not a soft ``rejected``: it records "I want changes",
#: which closes this gate and invites the agent to draft again, while ``rejected`` closes the
#: subject. Neither confirms anything.
DECISIONS = ("approved", "rejected", "revised")

#: V1 is single-currency; the column exists so an amount is never rendered without its unit, and so
#: a later multi-currency workspace is a data change rather than a migration of every stored gate.
DEFAULT_GATE_CURRENCY = "USD"

_GATE_NAMESPACE = uuid5(NAMESPACE_URL, "clue:lane-d:d4:directive-confirmation-gate")
_PRODUCT_SELECTION_GATE_NAMESPACE = uuid5(
    NAMESPACE_URL, "clue:production-context:s5:product-selection-gate"
)
_PRODUCT_SET_SELECTION_GATE_NAMESPACE = uuid5(
    NAMESPACE_URL, "clue:arv2:onboarding:product-set-selection-gate"
)
_ICP_ARTIFACT_GATE_NAMESPACE = uuid5(NAMESPACE_URL, "clue:arv2:onboarding:icp-artifact-gate")

_GATE_COLUMNS = (
    "gate_id, workspace_id, project_id, thread_id, turn_id, kind, subject_ref, "
    "subject_revision, expected_subject_sha256, subject_snapshot, permitted_decisions, "
    "max_spend_cents, currency, addressee_user_id, created_at, snapshot_erased_at, "
    "snapshot_erasure_reason"
)
_ANSWER_COLUMNS = (
    "gate_id, workspace_id, turn_id, action_ref, decision, expected_subject_sha256, "
    "decision_payload, selected_option_ref, answered_by_user_id, answered_at"
)


def money_text(amount: Decimal) -> str:
    """The one canonical spelling of a cent amount.

    ``Decimal("1200")``, ``Decimal("1200.00")`` and the ``numeric(20,4)`` column's
    ``Decimal("1200.0000")`` are the same amount and must produce the same bytes, or a request
    digest computed before the write would not match one computed after it.
    """

    normalized = amount.normalize()
    # ``normalize`` yields scientific notation for trailing-zero integers (1200 -> 1.2E+3);
    # ``'f'`` forces the plain form, which is what a human and a digest both want.
    return format(normalized, "f")


class GateAlreadyAnswered(ValueError):
    """This gate already holds an answer, so no second answer may be recorded.

    Carries the existing answer so a caller can tell an idempotent replay (same turn, same
    decision) from a genuine double-answer by a second actor or a second click.
    """

    def __init__(self, existing: AgentGateAnswerRow) -> None:
        super().__init__("this gate was already answered")
        self.existing = existing


class AgentGateRow(BaseModel):
    """One presented gate — immutable by trigger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: UUID
    workspace_id: str
    project_id: str
    thread_id: str
    turn_id: UUID
    kind: str
    subject_ref: str
    subject_revision: int | None
    expected_subject_sha256: str
    subject_snapshot: dict[str, JsonValue]
    permitted_decisions: tuple[str, ...]
    max_spend_cents: Decimal | None
    currency: str | None
    addressee_user_id: str
    created_at: datetime
    snapshot_erased_at: datetime | None = None
    snapshot_erasure_reason: str | None = None

    @property
    def snapshot_available(self) -> bool:
        return self.snapshot_erased_at is None


@dataclass(frozen=True, slots=True)
class AgentGateSubjectBinding:
    """Body-free DSAR reach for one subject copied into a gate snapshot."""

    subject_entity_id: UUID
    binding_kind: str

    def __post_init__(self) -> None:
        if not self.binding_kind.strip():
            raise ValueError("gate subject binding_kind cannot be empty")


class AgentGateAnswerRow(BaseModel):
    """The insert-once record that a gate was answered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: UUID
    workspace_id: str
    turn_id: UUID
    action_ref: str
    decision: str
    expected_subject_sha256: str
    decision_payload: dict[str, JsonValue]
    selected_option_ref: str | None
    answered_by_user_id: str
    answered_at: datetime


@dataclass(frozen=True, slots=True)
class GateView:
    """A gate plus its answer, if it has one. ``open`` is derived, never stored."""

    gate: AgentGateRow
    answer: AgentGateAnswerRow | None

    @property
    def is_open(self) -> bool:
        return self.answer is None and self.gate.snapshot_available


def directive_confirmation_gate_id(
    *,
    workspace_id: str,
    turn_id: UUID,
    subject_ref: str,
    expected_subject_sha256: str,
) -> UUID:
    """Derive the gate id for one presentation of one exact subject in one turn.

    Derived rather than minted so that re-running a turn (a fleet retry, a replayed plan step)
    presents *the same gate* instead of a second one addressing the same person about the same
    directive. The digest is in the key because a re-drafted directive is genuinely a different
    thing to approve and deserves its own gate.
    """

    framed = "".join(
        f"{len(part)}:{part}"
        for part in (workspace_id, str(turn_id), subject_ref, expected_subject_sha256)
    )
    return uuid5(_GATE_NAMESPACE, framed)


def product_selection_gate_id(
    *,
    workspace_id: str,
    turn_id: UUID,
    subject_ref: str,
    expected_subject_sha256: str,
) -> UUID:
    """Derive one immutable selection gate for one pinned catalog presentation."""

    framed = "".join(
        f"{len(part)}:{part}"
        for part in (workspace_id, str(turn_id), subject_ref, expected_subject_sha256)
    )
    return uuid5(_PRODUCT_SELECTION_GATE_NAMESPACE, framed)


def product_set_selection_gate_id(
    *,
    workspace_id: str,
    turn_id: UUID,
    subject_ref: str,
    expected_subject_sha256: str,
) -> UUID:
    """Derive one immutable product-SET selection gate for one pinned catalog presentation
    (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.3; a project targets a set of products, ruling P1)."""

    framed = "".join(
        f"{len(part)}:{part}"
        for part in (workspace_id, str(turn_id), subject_ref, expected_subject_sha256)
    )
    return uuid5(_PRODUCT_SET_SELECTION_GATE_NAMESPACE, framed)


def icp_artifact_gate_id(
    *,
    workspace_id: str,
    project_id: str,
    subject_ref: str,
    expected_subject_sha256: str,
) -> UUID:
    """Derive one immutable ICP gate for one exact ``brand_knowledge_document`` (ARV2 O6).

    Keyed on the **project**, not the presenting turn, and on the document ref plus its digest —
    the same four coordinates the ``agent_gate_one_icp_subject`` unique index enforces. One project
    asking about one exact ICP document is one question, however many turns reach for it.
    """

    framed = "".join(
        f"{len(part)}:{part}"
        for part in (workspace_id, project_id, subject_ref, expected_subject_sha256)
    )
    return uuid5(_ICP_ARTIFACT_GATE_NAMESPACE, framed)


async def insert_gate(
    conn: AsyncConnection,
    *,
    gate_id: UUID,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    turn_id: UUID,
    kind: str,
    subject_ref: str,
    subject_revision: int | None,
    expected_subject_sha256: str,
    subject_snapshot: dict[str, JsonValue],
    max_spend_cents: Decimal | None,
    currency: str | None,
    addressee_user_id: str,
    permitted_decisions: tuple[str, ...] = DECISIONS,
    subject_bindings: Sequence[AgentGateSubjectBinding] = (),
) -> tuple[AgentGateRow, bool]:
    """Present one gate, or replay it. Returns ``(row, created)``.

    A repeat presentation of the same derived id is a replay and returns the stored row — the row
    is immutable, so the stored values are authoritative and the caller's recomputed ones are
    simply discarded. That is deliberate: if the amount changed between the two presentations, the
    number the human is looking at is the one that was written first, and a launch verifying
    against it is verifying against what was actually shown.
    """

    if kind not in GATE_KINDS:
        raise ValueError(f"unknown gate kind {kind!r}")
    if not permitted_decisions or len(set(permitted_decisions)) != len(permitted_decisions):
        raise ValueError("a gate must have a non-empty unique decision vocabulary")
    unsupported = set(permitted_decisions) - set(DECISIONS)
    if unsupported:
        raise ValueError(f"unknown gate decision(s) {sorted(unsupported)!r}")
    if (max_spend_cents is None) != (currency is None):
        raise ValueError("gate amount and currency must either both be present or both be absent")
    inserted = (
        (
            await conn.execute(
                text(
                    "INSERT INTO agent_gate "
                    "(gate_id, workspace_id, project_id, thread_id, turn_id, kind, subject_ref, "
                    " subject_revision, expected_subject_sha256, subject_snapshot, "
                    " permitted_decisions, max_spend_cents, currency, addressee_user_id) "
                    "VALUES (:gate_id, :workspace_id, :project_id, :thread_id, :turn_id, :kind, "
                    " :subject_ref, :subject_revision, :digest, CAST(:snapshot AS jsonb), "
                    " CAST(:permitted_decisions AS text[]), :max_spend, :currency, :addressee) "
                    f"ON CONFLICT (gate_id) DO NOTHING RETURNING {_GATE_COLUMNS}"
                ),
                {
                    "gate_id": gate_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "kind": kind,
                    "subject_ref": subject_ref,
                    "subject_revision": subject_revision,
                    "digest": expected_subject_sha256,
                    "snapshot": _dumps(subject_snapshot),
                    "permitted_decisions": list(permitted_decisions),
                    "max_spend": max_spend_cents,
                    "currency": currency,
                    "addressee": addressee_user_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    created = inserted is not None
    row = (
        AgentGateRow.model_validate(_decoded(dict(inserted)))
        if inserted is not None
        else await _gate_row(conn, workspace_id=workspace_id, gate_id=gate_id)
    )
    if row is None:
        # Practically unreachable (the id is derived from the workspace), and refusing beats
        # leaking that another tenant holds this id.
        raise ValueError("this gate identity exists outside the requested workspace")
    for binding in subject_bindings:
        await conn.execute(
            text(
                "INSERT INTO agent_gate_subject "
                "(workspace_id, gate_id, subject_entity_id, binding_kind) "
                "VALUES (:workspace, :gate, :subject, :kind) ON CONFLICT DO NOTHING"
            ),
            {
                "workspace": workspace_id,
                "gate": gate_id,
                "subject": binding.subject_entity_id,
                "kind": binding.binding_kind,
            },
        )
    return row, created


async def get_gate(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    gate_id: UUID,
) -> GateView | None:
    """Read one gate **inside one workspace**, with its answer if it has one.

    A cross-workspace read is a miss, not a refusal: existence is not leaked to a principal who
    cannot see the gate (the same rule D1's turn-action resolver follows).
    """

    gate = await _gate_row(conn, workspace_id=workspace_id, gate_id=gate_id)
    if gate is None:
        return None
    answer = await _answer_row(conn, workspace_id=workspace_id, gate_id=gate_id)
    return GateView(gate=gate, answer=answer)


async def insert_gate_answer(
    conn: AsyncConnection,
    *,
    gate_id: UUID,
    workspace_id: str,
    turn_id: UUID,
    action_ref: str,
    decision: str,
    expected_subject_sha256: str,
    decision_payload: dict[str, JsonValue] | None = None,
    answered_by_user_id: str,
    selected_option_ref: str | None = None,
) -> AgentGateAnswerRow:
    """Record the one answer this gate will ever have.

    Raises :class:`GateAlreadyAnswered` when a row already exists — including when it records the
    *same* turn and decision. Idempotency is the caller's to decide, because "the same human
    clicked twice" and "a retried request re-lands the same act" need different responses and only
    the caller knows which it is looking at.
    """

    if decision not in DECISIONS:
        raise ValueError(f"unknown gate decision {decision!r}")
    payload = decision_payload or {}
    gate = await _gate_row(conn, workspace_id=workspace_id, gate_id=gate_id)
    if gate is None:
        raise ValueError("no such gate in the requested workspace")
    if not gate.snapshot_available:
        raise ValueError("an erased gate snapshot cannot be answered")
    if payload and selected_option_ref is not None:
        raise ValueError("a gate answer cannot carry both decision_payload and selected_option_ref")
    inserted = (
        (
            await conn.execute(
                text(
                    "INSERT INTO agent_gate_answer "
                    "(gate_id, workspace_id, turn_id, action_ref, decision, "
                    " expected_subject_sha256, decision_payload, selected_option_ref, "
                    " answered_by_user_id) "
                    "VALUES (:gate_id, :workspace_id, :turn_id, :action_ref, :decision, "
                    " :digest, CAST(:payload AS jsonb), :selected_option_ref, :user_id) "
                    f"ON CONFLICT (gate_id) DO NOTHING RETURNING {_ANSWER_COLUMNS}"
                ),
                {
                    "gate_id": gate_id,
                    "workspace_id": workspace_id,
                    "turn_id": turn_id,
                    "action_ref": action_ref,
                    "decision": decision,
                    "digest": expected_subject_sha256,
                    "payload": _dumps(payload),
                    "selected_option_ref": selected_option_ref,
                    "user_id": answered_by_user_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if inserted is not None:
        return AgentGateAnswerRow.model_validate(_decoded(dict(inserted)))
    existing = await _answer_row(conn, workspace_id=workspace_id, gate_id=gate_id)
    if existing is None:
        raise ValueError("this gate answer exists outside the requested workspace")
    raise GateAlreadyAnswered(existing)


async def gate_answer_for_turn(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
) -> AgentGateAnswerRow | None:
    """The gate answer this turn carried, if it carried one.

    The gate-authority half of D1's action receipt: an ordinary turn resolves here to ``None``, and
    a caller that requires gate authority must therefore refuse it.
    """

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_ANSWER_COLUMNS} FROM agent_gate_answer "
                    "WHERE workspace_id = :workspace_id AND turn_id = :turn_id"
                ),
                {"workspace_id": workspace_id, "turn_id": turn_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return AgentGateAnswerRow.model_validate(_decoded(dict(row))) if row is not None else None


async def open_gates_for_thread(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
) -> tuple[AgentGateRow, ...]:
    """Every unanswered gate of one thread, oldest first.

    "Unanswered" is an anti-join against the answer table — the derivation §6-D3 ratified — so a
    thread's approval state cannot drift from the record of what was actually decided.
    """

    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {', '.join(f'g.{column}' for column in _GATE_COLUMNS.split(', '))} "
                    "FROM agent_gate g "
                    "LEFT JOIN agent_gate_answer a "
                    "  ON a.gate_id = g.gate_id AND a.workspace_id = g.workspace_id "
                    "WHERE g.workspace_id = :workspace_id AND g.thread_id = :thread_id "
                    "  AND a.gate_id IS NULL AND g.snapshot_erased_at IS NULL "
                    "ORDER BY g.created_at, g.gate_id"
                ),
                {"workspace_id": workspace_id, "thread_id": thread_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(AgentGateRow.model_validate(_decoded(dict(row))) for row in rows)


async def redact_gate_snapshots_for_subject(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_entity_id: UUID,
    reason_code: str,
) -> tuple[UUID, ...]:
    """Irreversibly blank every gate snapshot bound to ``subject_entity_id``.

    Gate identity, subject reference, digest, version, and answer receipt remain body-free audit
    facts. The exact snapshot becomes ``{}`` once, and deterministic privacy events make replay
    idempotent without ever reconstructing the erased value.
    """

    gate_ids = tuple(
        (
            await conn.execute(
                text(
                    "SELECT binding.gate_id FROM agent_gate_subject binding "
                    "WHERE binding.workspace_id=:workspace "
                    "AND binding.subject_entity_id=:subject ORDER BY binding.gate_id"
                ),
                {
                    "workspace": workspace_id,
                    "subject": subject_entity_id,
                },
            )
        ).scalars()
    )
    if gate_ids:
        await conn.execute(
            text(
                "UPDATE agent_gate SET subject_snapshot='{}'::jsonb, "
                "snapshot_erased_at=now(), snapshot_erasure_reason=:reason "
                "WHERE workspace_id=:workspace AND gate_id=ANY(CAST(:gates AS uuid[])) "
                "AND snapshot_erased_at IS NULL"
            ),
            {
                "workspace": workspace_id,
                "gates": list(gate_ids),
                "reason": reason_code,
            },
        )
    for gate_id in gate_ids:
        await conn.execute(
            text(
                "INSERT INTO agent_privacy_event "
                "(event_id, workspace_id, subject_entity_id, turn_id, action, reason_code) "
                "SELECT :event, g.workspace_id, :subject, g.turn_id, "
                "'gate_snapshot_redacted', :reason FROM agent_gate g "
                "WHERE g.gate_id=:gate AND g.workspace_id=:workspace "
                "ON CONFLICT (event_id) DO NOTHING"
            ),
            {
                "event": uuid5(
                    _GATE_NAMESPACE,
                    f"privacy:{workspace_id}:{subject_entity_id}:{gate_id}",
                ),
                "workspace": workspace_id,
                "subject": subject_entity_id,
                "gate": gate_id,
                "reason": reason_code,
            },
        )
    return gate_ids


async def _gate_row(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    gate_id: UUID,
) -> AgentGateRow | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_GATE_COLUMNS} FROM agent_gate "
                    "WHERE gate_id = :gate_id AND workspace_id = :workspace_id"
                ),
                {"gate_id": gate_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return AgentGateRow.model_validate(_decoded(dict(row))) if row is not None else None


async def _answer_row(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    gate_id: UUID,
) -> AgentGateAnswerRow | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_ANSWER_COLUMNS} FROM agent_gate_answer "
                    "WHERE gate_id = :gate_id AND workspace_id = :workspace_id"
                ),
                {"gate_id": gate_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return AgentGateAnswerRow.model_validate(_decoded(dict(row))) if row is not None else None


def _dumps(value: dict[str, JsonValue]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _decoded(row: dict[str, object]) -> dict[str, object]:
    """Decode the one ``jsonb`` column, which asyncpg may hand back as text or bytes."""

    for key in ("subject_snapshot", "decision_payload"):
        value = row.get(key)
        if isinstance(value, bytes | bytearray | str):
            row[key] = json.loads(value)
    return row
