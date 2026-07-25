"""M11 (tier-4 LLM synthesis) api-root wiring — the home M11 fills (phase-3 pre-flight PF-7).

Kept in its OWN module so M10 / M11 / M12 never co-edit ``api/composition.py`` when they integrate
(distinct files never 3-way-conflict; the shared ``load_research_packs`` body is replaced by the
``RESEARCH_PACK_LOADERS`` registry). M11 fills :func:`register_synthesis_wiring`:

* bind the Exa Deep / Parallel Task resolvers via ``sources.bind_resolver("exa_deep", …)``
  / ``("parallel_task", ParallelTaskResolver())``. The resolver classes + provider SDKs live under
  ``resolvers/exa`` / ``resolvers/parallel`` (forbidden-SDK contract), never ``synthesis``;
* append any tier-4 synthesis field-pack loader to
  :data:`~clue_api.composition.RESEARCH_PACK_LOADERS` (the seeded synthesis fields already
  live in the core pack);
* register the synthesis aspect workers, judge-gated per
  :data:`~clue_api.composition.VERIFICATION_GATE_ORDER` (faithfulness M9.3 → promotion).

**M11.1** binds Exa Deep to the already-seeded ``exa_deep`` manifest. **M11.2 (this commit)** also
binds Parallel Task to the seeded ``parallel_task`` manifest — a *second*, independent tier-4
provider behind the identical seam, so running one, the other, or both (cross-provider convergence)
is purely a Source-Planner/config choice. Both resolvers are account-scoped — each returns ``[]``
for a contact entity / contact-class field, so binding to the ``entity_scope=BOTH`` manifests cannot
leak a ``contact.facet.*`` claim (the personal-data firewall; PF-8 was dropped as harmful, so the
firewall is field-routing, not a manifest edit).
**M11.3** adds the judge-gated synthesis workers + the verification-health metric. (The deferred
``PreSpendGate.check`` wiring for the tier-4 spend path — M9.1 AC6 — lands here at integration,
alongside the M4/M8 gate routing.)
"""

from __future__ import annotations

from clue_research.resolvers import (
    AccountLookup,
    register_exa_deep_resolver,
    register_parallel_task_resolver,
)


def register_synthesis_wiring(*, accounts: AccountLookup | None = None) -> None:
    """Bind the tier-4 synthesis resolvers at the api root (M11.1 Exa Deep; M11.2 Parallel Task).

    Both bind to their already-seeded manifests (``exa_deep`` / ``parallel_task``) behind the same
    :class:`~clue_research.resolvers.GroundedSynthesisResolver` seam — the waterfall dispatches to
    whichever a field's ``tier_plan`` names, with no knowledge of either provider. ``accounts`` is
    the orchestrator's :class:`~clue_research.resolvers.AccountLookup` (entity_id → the resolved
    :class:`~clue_core.AccountEntity`) the resolvers target-lock the query with; the M6/M8
    deep-run composition supplies it. Idempotent (last write wins per key).
    """
    register_exa_deep_resolver(accounts=accounts)
    register_parallel_task_resolver(accounts=accounts)
