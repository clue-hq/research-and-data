"""M11 (tier-4 LLM synthesis) api-root wiring — the home M11 fills (phase-3 pre-flight PF-7).

Kept in its OWN module so M10 / M11 / M12 never co-edit ``api/composition.py`` when they integrate
(distinct files never 3-way-conflict; the shared ``load_research_packs`` body is replaced by the
``RESEARCH_PACK_LOADERS`` registry). M11 fills :func:`register_synthesis_wiring`:

* bind the Exa Deep / Parallel Task resolvers via ``sources.bind_resolver("exa_deep", …)``
  / ``("parallel_task", ParallelTaskResolver())``. The resolver classes + provider SDKs live under
  ``resolvers/exa`` / ``resolvers/parallel`` (forbidden-SDK contract), never ``synthesis``;
* append any tier-4 synthesis field-pack loader to
  :data:`~clue_research.api.composition.RESEARCH_PACK_LOADERS` (the seeded synthesis fields already
  live in the core pack);
* register the synthesis aspect workers, judge-gated per
  :data:`~clue_research.api.composition.VERIFICATION_GATE_ORDER` (faithfulness M9.3 → promotion).

**M11.1 (this commit)** binds Exa Deep to the already-seeded ``exa_deep`` manifest. The resolver is
account-scoped — it returns ``[]`` for a contact entity / contact-class field, so binding it to the
``entity_scope=BOTH`` ``exa_deep`` manifest cannot leak a ``contact.facet.*`` claim (the
personal-data firewall; PF-8 was dropped as harmful, so the firewall is field-routing, not a
manifest edit).
**M11.2** adds the Parallel binding; **M11.3** adds the judge-gated synthesis workers + the
verification-health metric. (The deferred ``PreSpendGate.check`` wiring for the tier-4 spend path —
M9.1 AC6 — lands here at integration, alongside the M4/M8 gate routing.)
"""

from __future__ import annotations

from clue_research.resolvers import AccountLookup, register_exa_deep_resolver


def register_synthesis_wiring(*, accounts: AccountLookup | None = None) -> None:
    """Bind the tier-4 synthesis resolvers at the api root (M11.1 Exa Deep; M11.2 Parallel Task).

    ``accounts`` is the orchestrator's :class:`~clue_research.resolvers.AccountLookup` (entity_id
    → the resolved :class:`~clue_research.core.AccountEntity`) the resolver target-locks the query
    with; the M6/M8 deep-run composition supplies it. Idempotent (last write wins per key).
    """
    register_exa_deep_resolver(accounts=accounts)
