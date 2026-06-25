"""M10 api-root wiring: the compliance field-pack registration through the shared PF-7
``RESEARCH_PACK_LOADERS`` registry. Pure (no DB) — mirrors ``test_narrative_wiring`` so M10's pack
loads alongside M8's deep pack and M12's narrative pack without any milestone co-editing
``load_research_packs`` (the M2×M3-class collision the pre-flight avoids)."""

from __future__ import annotations

from clue_research.api import composition
from clue_research.api.compliance_wiring import register_compliance_wiring
from clue_research.compliance import load_compliance_pack


def test_register_compliance_wiring_appends_pack_idempotently() -> None:
    saved = list(composition.RESEARCH_PACK_LOADERS)
    try:
        composition.RESEARCH_PACK_LOADERS[:] = [
            loader for loader in saved if loader is not load_compliance_pack
        ]
        register_compliance_wiring()
        register_compliance_wiring()  # idempotent — a second call must not duplicate
        assert composition.RESEARCH_PACK_LOADERS.count(load_compliance_pack) == 1
    finally:
        composition.RESEARCH_PACK_LOADERS[:] = saved  # never leak global state to sibling tests
