"""Idempotency key derivation — the two durable-execution key shapes (Beat-0; M7.4).

Durable execution is idempotent on two keys (substrate §5c): a per-account research *step*
``(account_run, entity, field, tier)`` and a per-campaign *phase* ``(project_run, phase)``. The
key *derivation* is a pure, dependency-free function, so it lives in ``core`` (M0.2) where every
package shares one definition; the ledger-backed ``idempotent(...)`` context manager that *uses*
these keys (and its Postgres ``idempotency_ledger`` table) is built on the M7 branch in ``durable``.

Keys are stable across retries and process restarts (no clock, no randomness) — the same inputs
always hash to the same key — which is exactly what makes a retried step or re-entered phase
deduplicate instead of double-spending.
"""

from __future__ import annotations

import hashlib

from clue_core.enums import IdempotencyScope, ProjectPhase
from clue_core.field import FieldKey
from clue_core.primitives import (
    EntityId,
    ProjectRunId,
    RunId,
    SourceTier,
)

# Field separator that cannot occur in any well-formed part (UUIDs, ints, field keys, enum values)
# — so distinct tuples can never collide by concatenation (e.g. ("a","bc") vs ("ab","c")).
_SEP = "\x1f"


def idempotency_key(scope: IdempotencyScope, *parts: object) -> str:
    """Derive a stable idempotency key for ``scope`` from ``parts``.

    Deterministic: the same ``(scope, parts)`` always yields the same key, with no clock or
    randomness, so it survives retries and restarts. The returned key is ``"{scope}:{sha256}"`` —
    scope-prefixed for readability/debuggability, hashed for a fixed-width, collision-resistant key.
    """
    payload = _SEP.join(str(part) for part in (scope, *parts))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{scope}:{digest}"


def account_step_key(
    account_run_id: RunId,
    entity_id: EntityId,
    field_key: FieldKey,
    source_tier: SourceTier,
) -> str:
    """The idempotency key for one per-account research step ``(account_run, entity, field, tier)``
    (substrate §5c). A retried resolver call for the same field at the same tier reuses this key and
    does not re-spend."""
    return idempotency_key(
        IdempotencyScope.ACCOUNT_STEP, account_run_id, entity_id, field_key, source_tier
    )


def phase_key(project_run_id: ProjectRunId, phase: ProjectPhase) -> str:
    """The idempotency key for one campaign-run phase ``(project_run, phase)`` (substrate §5c). A
    re-entered phase reuses this key, so the phase commits its effects exactly once."""
    return idempotency_key(IdempotencyScope.PROJECT_PHASE, project_run_id, phase)
