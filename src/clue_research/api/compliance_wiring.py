"""M10 (compliance & personal-data) api-root wiring — the home M10 fills (phase-3 pre-flight PF-7).

Own module so M10 / M11 / M12 never co-edit ``api/composition.py``. M10 fills
:func:`register_compliance_wiring`:

* **[done — this commit]** append M10's field-pack loader (``contact.jurisdiction`` + shorter
  ``contact.facet.*`` retention/freshness TTLs) to
  :data:`~clue_research.api.composition.RESEARCH_PACK_LOADERS` — via M10's OWN wiring module, never
  co-editing ``load_research_packs`` (PF-7), exactly as M12's ``register_narrative_wiring`` appends
  ``load_narrative_pack``;
* **[deferred — needs the VERIFICATION phase handler]** inject the ``core.compliance.UseGate`` impl
  (``compliance.UseGateImpl``), registered **last** in the verification sequence per
  :data:`~clue_research.api.composition.VERIFICATION_GATE_ORDER` — after M9.4 identity-binding /
  M9.3 faithfulness (Doc D §7: "is it this person?" before "may we use it?"). The live call site is
  the ``CampaignPhase.VERIFICATION`` handler, which does not exist yet;
* **[deferred]** wire the DSAR / retention sweep (``compliance.RetentionSweep``) — drain
  ``core.verification.Freshness.due_for_age_out`` → M10.5 tombstone the objected + retention-EXPIRED
  claims **before** the next merge read, so ``current_value`` / the M12 handoff stop seeing them
  (decisions D-OBJ / D-EXP). This is the load-bearing ordering invariant (CLAUDE.md
  ``[M9.5×M1.2/M10.5]``) and lands with the HANDOFF-phase pre-read sweep;
* **[deferred]** wire ``ClientPolicy.gather_scope`` into the M4.6 Source Planner.
"""

from __future__ import annotations

from clue_research.api.composition import RESEARCH_PACK_LOADERS
from clue_research.compliance import load_compliance_pack


def register_compliance_wiring() -> None:
    """Register the M10 compliance field pack at the api root (idempotent).

    Appends :func:`clue_research.compliance.load_compliance_pack` to
    :data:`~clue_research.api.composition.RESEARCH_PACK_LOADERS` so a deep run registers
    ``contact.jurisdiction`` and the shorter personal-data retention/freshness TTLs (a no-op if
    already appended — safe to call more than once, mirroring ``register_narrative_wiring``).

    The runtime governance seams M10 supplies — the ``UseGateImpl`` (the last verification gate),
    the ``RetentionSweep`` tombstone-before-merge-read pass, and the ``ClientPolicy.gather_scope``
    source-scoping hook — are injected at their live call sites (the ``CampaignPhase.VERIFICATION``
    handler and the HANDOFF-phase pre-read sweep) as those land; see the module docstring.
    """
    if load_compliance_pack not in RESEARCH_PACK_LOADERS:
        RESEARCH_PACK_LOADERS.append(load_compliance_pack)
