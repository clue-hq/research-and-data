"""M13.3 — the ``LearningLoop`` implementation (compute_yield / propose / promote).

Ties the pieces together: :func:`~clue_research.review.yield_metrics.compute_yield` (the metrics),
the pure reweighters (``reweight.py``), the ``config_revision`` ledger (``config_revision.py``), and
the versioned config stores (``icp``) — with the injected :class:`~clue_research.core.BacktestGate`
gating a rubric promotion. The loop only ever *proposes* a versioned revision and, on a gated
``promote``, writes the existing store (a new ``icp_spec`` version for a rubric, a
``source_profile_override`` version for a profile); the engine reads the stores, not the ledger, so
reproducibility holds for free. ``review`` may import ``icp``/``sources`` (services); the backtest's
``verification``/``evals`` dependency arrives only through the ``core.BacktestGate`` seam.
"""

from __future__ import annotations

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    BacktestGate,
    ConfigRevisionStatus,
    ConfigRevisionTarget,
    ICPCreatedFrom,
    PromotionMode,
)
from clue_research.db import ConnFactory, transaction
from clue_research.icp import (
    WeightedSource,
    create_icp_spec,
    get_active_icp,
    get_source_profile,
    register_source_profile_override,
    reweighted,
    rubric_from_slot,
    rubric_to_slot,
)
from clue_research.review.config_revision import (
    ConfigRevision,
    ConfigRevisionId,
    get_config_revision,
    latest_config_revision,
    mark_promoted,
    mark_rejected,
    record_config_revision,
)
from clue_research.review.labeled_dataset import read_labeled_dataset
from clue_research.review.reweight import (
    DEFAULT_REWEIGHT_POLICY,
    ReweightPolicy,
    reweight_scoring_rubric,
    reweight_source_profile,
)
from clue_research.review.yield_metrics import YieldMetrics, compute_yield


class LearningLoopError(RuntimeError):
    """A learning-loop precondition failed (e.g. no active ICP spec / rubric to reweight)."""


class PromotionBlocked(RuntimeError):
    """A ``promote`` was refused: an out-of-bounds move without ``PromotionMode.HUMAN``, a failed
    backtest guardrail, or a revision that is not in ``proposed`` status."""


class LearningLoopImpl:
    """The M13.3 ``LearningLoop`` — proposes versioned reweights and promotes them via the gates.

    ``backtest_gate`` is the injected ``core.BacktestGate`` (the api root wires the concrete over
    the M9.6 eval harness); ``None`` skips the backtest (standalone / unit). ``policy`` carries the
    reweight bounds (policy as data)."""

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        backtest_gate: BacktestGate | None = None,
        policy: ReweightPolicy = DEFAULT_REWEIGHT_POLICY,
    ) -> None:
        self._conn_factory = conn_factory
        self._gate = backtest_gate
        self._policy = policy

    async def compute_yield(
        self, *, client_id: str, icp_key: str, icp_spec_version: int | None = None
    ) -> YieldMetrics:
        """The per-(field-class, source) yield for a scope+version (spec §M13.3 AC)."""
        async with self._conn_factory() as conn:
            return await compute_yield(
                conn, client_id=client_id, icp_key=icp_key, icp_spec_version=icp_spec_version
            )

    async def propose_source_profile_revision(
        self,
        *,
        client_id: str,
        icp_key: str,
        pack_key: str,
        icp_spec_version: int,
        proposed_by: str | None = None,
    ) -> ConfigRevision:
        """Reweight a pack's source profile from yield → a new ``proposed`` source-profile revision.

        Bounded (each source moves ≤1 ordinal level; never zeroed). The payload is the full new
        pack-wide slot; ``promote`` writes it as a ``source_profile_override`` version."""
        async with self._conn_factory() as conn:
            resolved = await get_source_profile(
                conn, pack_key, client_id=client_id, icp_key=icp_key
            )
            metrics = await compute_yield(
                conn, client_id=client_id, icp_key=icp_key, icp_spec_version=icp_spec_version
            )
            new_sources, moves = reweight_source_profile(
                resolved.default, metrics, policy=self._policy
            )
            payload: dict[str, JsonValue] = {
                "pack_key": pack_key,
                "field_class": None,
                "weighted_sources": [s.model_dump(mode="json") for s in new_sources],
            }
            parent = await latest_config_revision(
                conn,
                client_id=client_id,
                icp_key=icp_key,
                target=ConfigRevisionTarget.SOURCE_PROFILE,
            )
            return await record_config_revision(
                conn,
                target=ConfigRevisionTarget.SOURCE_PROFILE,
                client_id=client_id,
                icp_key=icp_key,
                icp_spec_version=icp_spec_version,
                payload_json=payload,
                parent_revision=parent.id if parent is not None else None,
                derived_from={
                    "pack_key": pack_key,
                    "n_sources": len(metrics.sources),
                    "has_downstream_signal": metrics.has_downstream_signal,
                },
                explanation=moves,
                within_bounds=True,  # the ordinal one-level cap is always within bounds
                proposed_by=proposed_by,
            )

    async def propose_scoring_rubric_revision(
        self, *, client_id: str, icp_key: str, proposed_by: str | None = None
    ) -> ConfigRevision:
        """Reweight the active scoring rubric from the labeled dataset → a new ``proposed`` rubric
        revision (decomposed/explainable). ``within_bounds`` is ``False`` when a capped move bit (so
        ``promote`` requires ``PromotionMode.HUMAN``)."""
        async with self._conn_factory() as conn:
            active = await get_active_icp(conn, client_id, icp_key)
            if active is None:
                raise LearningLoopError(f"no active ICP spec for ({client_id!r}, {icp_key!r})")
            rubric = rubric_from_slot(active.scoring_rubric)
            if rubric is None:
                raise LearningLoopError(
                    f"active ICP spec ({client_id!r}, {icp_key!r}) carries no scoring rubric"
                )
            dataset = await read_labeled_dataset(
                conn, client_id=client_id, icp_key=icp_key, icp_spec_version=active.version
            )
            fit_w, intent_w, moves, within = reweight_scoring_rubric(
                rubric, dataset, policy=self._policy
            )
            new_rubric = reweighted(
                rubric,
                fit_weights=fit_w,
                intent_weights=intent_w,
                feedback_basis={
                    "source": "m13.3_learning_loop",
                    "n_labeled_rows": len(dataset),
                    "within_bounds": within,
                },
            )
            parent = await latest_config_revision(
                conn,
                client_id=client_id,
                icp_key=icp_key,
                target=ConfigRevisionTarget.SCORING_RUBRIC,
            )
            return await record_config_revision(
                conn,
                target=ConfigRevisionTarget.SCORING_RUBRIC,
                client_id=client_id,
                icp_key=icp_key,
                icp_spec_version=active.version,
                payload_json=rubric_to_slot(new_rubric),
                parent_revision=parent.id if parent is not None else None,
                derived_from={"dataset_rows": len(dataset)},
                explanation=moves,
                within_bounds=within,
                proposed_by=proposed_by,
            )

    async def promote(
        self,
        revision_id: ConfigRevisionId,
        *,
        mode: PromotionMode = PromotionMode.AUTO,
        promoted_by: str | None = None,
        tolerance: float = 0.0,
    ) -> int:
        """Promote a proposed revision through the gates and write the versioned store; returns the
        store version produced (the ``applied_version``).

        Gate 1 (bounds): an out-of-bounds move (``within_bounds=False``) requires
        ``PromotionMode.HUMAN``. Gate 2 (backtest, rubric): the injected ``BacktestGate`` blocks
        a rubric revision that regresses golden-set accuracy. Raises :class:`PromotionBlocked` on
        any refusal — active config is never mutated in place."""
        async with self._conn_factory() as conn:
            # FOR UPDATE: serialize against a concurrent promote of this revision, so two callers
            # can't both pass the gate and double-apply (orphaning a store version).
            rev = await get_config_revision(conn, revision_id, for_update=True)
            if rev is None:
                raise LearningLoopError(f"config_revision {revision_id} not found")
            if rev.status is not ConfigRevisionStatus.PROPOSED:
                raise PromotionBlocked(
                    f"revision {revision_id} is {rev.status.value}, not proposed"
                )
            if not rev.within_bounds and mode is not PromotionMode.HUMAN:
                raise PromotionBlocked(
                    "out-of-bounds reweight requires PromotionMode.HUMAN approval"
                )
            if rev.target is ConfigRevisionTarget.SCORING_RUBRIC and self._gate is not None:
                verdict = await self._gate.backtest(
                    rev.payload_json,  # type: ignore[arg-type]  # the serialized rubric slot
                    client_id=rev.client_id,
                    icp_key=rev.icp_key,
                    baseline_version=rev.icp_spec_version,
                    tolerance=tolerance,
                )
                if not verdict.passed:
                    raise PromotionBlocked(
                        f"backtest blocked promotion: {verdict.detail or 'golden-set regression'}"
                    )
            applied_version = await self._apply(conn, rev)
            if not await mark_promoted(
                conn, revision_id, applied_version=applied_version, promoted_by=promoted_by
            ):
                # The row left ``proposed`` between the locked read and here — fail closed rather
                # than leave an applied store version with no promoted ledger row (defence in depth;
                # the FOR UPDATE lock above should already prevent this).
                raise PromotionBlocked(f"revision {revision_id} was concurrently resolved")
            return applied_version

    async def reject(self, revision_id: ConfigRevisionId) -> None:
        """Reject a proposed revision (never applied)."""
        async with self._conn_factory() as conn:
            rev = await get_config_revision(conn, revision_id)
            if rev is None:
                raise LearningLoopError(f"config_revision {revision_id} not found")
            await mark_rejected(conn, revision_id)

    async def _apply(self, conn: AsyncConnection, rev: ConfigRevision) -> int:
        if rev.target is ConfigRevisionTarget.SCORING_RUBRIC:
            return await self._apply_rubric(conn, rev)
        return await self._apply_source_profile(conn, rev)

    async def _apply_rubric(self, conn: AsyncConnection, rev: ConfigRevision) -> int:
        """Write the proposed rubric as a NEW active ICP-spec version, carrying the **active**
        spec's other slots forward unchanged (only the rubric moves).

        Refuses a **stale** proposal — one derived from a version that is no longer active (a client
        edit landed a newer version in between): promoting it would archive the newer version and
        silently revert its non-rubric edits. The operator must re-propose against the current
        version. Reproducibility holds either way: prior versions stay byte-identical."""
        active = await get_active_icp(conn, rev.client_id, rev.icp_key)
        if active is None or active.version != rev.icp_spec_version:
            raise PromotionBlocked(
                f"stale rubric proposal: derived from v{rev.icp_spec_version}, but the active ICP "
                f"spec is v{active.version if active else None} — re-propose against current"
            )
        spec = await create_icp_spec(
            conn,
            client_id=rev.client_id,
            icp_key=rev.icp_key,
            created_from=ICPCreatedFrom.FEEDBACK_REWEIGHT,
            field_keys=active.field_keys,
            enabled_packs=active.enabled_packs,
            discovery_strategy=active.discovery_strategy,
            source_profile_ref=active.source_profile_ref,
            scoring_rubric=rev.payload_json,  # type: ignore[arg-type]  # the rubric slot
            activate=True,
            created_by=rev.promoted_by,
            label="m13.3 rubric reweight",
        )
        return spec.version

    async def _apply_source_profile(self, conn: AsyncConnection, rev: ConfigRevision) -> int:
        """Write the proposed source profile as a NEW ``source_profile_override`` version for the
        pack-wide slot (field_class=None)."""
        payload = rev.payload_json
        assert isinstance(payload, dict)  # the propose path always writes a dict payload
        pack_key = str(payload["pack_key"])
        sources = [WeightedSource.model_validate(s) for s in payload["weighted_sources"]]  # type: ignore[union-attr]
        next_version = (
            await conn.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM source_profile_override "
                    "WHERE pack_key = :p AND client_id = :c "
                    "AND icp_key IS NOT DISTINCT FROM :k AND field_class IS NULL"
                ),
                {"p": pack_key, "c": rev.client_id, "k": rev.icp_key},
            )
        ).scalar_one()
        await register_source_profile_override(
            conn,
            pack_key,
            rev.client_id,
            sources,
            field_class=None,
            icp_key=rev.icp_key,
            version=int(next_version),
        )
        return int(next_version)
