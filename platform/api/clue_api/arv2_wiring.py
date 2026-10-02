"""ARV2 composition hooks (PF-7 pattern: each lane appends its own pack loader).

Lives *outside* ``clue_api/arv2/`` on purpose: the ARV2 package may not import ``clue_api``
modules outside itself (Global Constraint 7, machine-checked by
``tests/arv2/test_import_guard.py``), so the edge to ``clue_api.composition`` is drawn here.
"""

from __future__ import annotations

from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.arv2.display.recipes import load_display_recipes
from clue_api.composition import RESEARCH_PACK_LOADERS


def register_arv2_wiring() -> None:
    """Append the ARV2 field pack and display recipes to the pack loaders (safe to call twice)."""
    if load_arv2_pack not in RESEARCH_PACK_LOADERS:
        RESEARCH_PACK_LOADERS.append(load_arv2_pack)
    if load_display_recipes not in RESEARCH_PACK_LOADERS:
        RESEARCH_PACK_LOADERS.append(load_display_recipes)
