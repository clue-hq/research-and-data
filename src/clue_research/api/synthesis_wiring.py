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

Until M11 lands this is a documented no-op so the seam + ownership home exist.
"""

from __future__ import annotations


def register_synthesis_wiring() -> None:
    """Bind the tier-4 synthesis resolvers + register their fields/workers at the api root.

    Filled by M11 (M11.1 Exa Deep, M11.2 Parallel Task, M11.3 field-wiring). Placeholder until then.
    """
