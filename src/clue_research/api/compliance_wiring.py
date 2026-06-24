"""M10 (compliance & personal-data) api-root wiring — the home M10 fills (phase-3 pre-flight PF-7).

Own module so M10 / M11 / M12 never co-edit ``api/composition.py``. M10 fills
:func:`register_compliance_wiring`:

* inject the ``core.compliance.UseGate`` impl, registered **last** in the verification sequence per
  :data:`~clue_research.api.composition.VERIFICATION_GATE_ORDER` — after M9.4 identity-binding /
  M9.3 faithfulness (Doc D §7: "is it this person?" before "may we use it?");
* append M10's field-pack loader (``contact.jurisdiction`` + shorter ``contact.facet.*`` retention/
  freshness TTLs) to :data:`~clue_research.api.composition.RESEARCH_PACK_LOADERS`;
* wire the DSAR / retention sweep — drain ``core.verification.Freshness.due_for_age_out`` →
  M10.5 tombstone the objected + retention-EXPIRED claims **before** the next merge read,
  so ``current_value`` / the M12 handoff stop seeing them (decisions D-OBJ / D-EXP);
* wire ``ClientPolicy.gather_scope`` into the M4.6 Source Planner.

Until M10 lands this is a documented no-op so the seam + ownership home exist.
"""

from __future__ import annotations


def register_compliance_wiring() -> None:
    """Inject the use gate + DSAR/retention sweep + jurisdiction fields at the api root.

    Filled by M10 (M10.1–M10.5). Placeholder until then.
    """
