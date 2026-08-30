"""The ad-assets lane's sync store facade (the ``IngestionJobStore`` / ``DescriptionStore`` shape).

Every method is one :class:`~lumen_api.design_store.DesignStoreBridge` call — one coroutine,
one loop, one transaction (the O5 rule) — over :mod:`clue_design.ad_assets`, returning the same
JSON shapes the DAL does.

**The three write methods here are governed** (D6, ruling R-D6-6): ``record_creatives``,
``create_card_version`` and ``link_pregenerated_assets`` are called only from
``lumen_api/toolbelt/ad_assets.py``, and ``tests/test_write_path_governance.py`` fails naming
the file and the line if any other module under ``lumen_api/`` or ``lumen_ingestion/`` calls
them. The reads are ungoverned, like every other read in the design app.
"""

from __future__ import annotations

from typing import Any, Optional

from clue_design import ad_assets as design_ad_assets
from lumen_api.design_store import DesignStoreBridge, default_workspace_id

JsonObject = dict[str, Any]

__all__ = ["AdAssetsStore"]


class AdAssetsStore:
    """Durable store for the Brand Ad Assets lane (Postgres, workspace-scoped).

    ``workspace_id`` defaults to the configured dev workspace exactly like the other design
    store facades; every request and worker path passes the resolved workspace explicitly.
    """

    def __init__(self, *, workspace_id: Optional[str] = None) -> None:
        self.workspace_id = workspace_id or default_workspace_id()
        self._bridge = DesignStoreBridge(self.workspace_id)

    # --- writes (governed) ---------------------------------------------------------------

    def record_creatives(self, creatives: list[JsonObject]) -> list[str]:
        return self._bridge._run(
            lambda conn: design_ad_assets.record_ad_creatives(
                conn, workspace_id=self.workspace_id, creatives=creatives
            )
        )

    def create_card_version(
        self,
        *,
        card_id: str,
        brand_kit_id: str,
        brand_kit_version: int,
        card: JsonObject,
        source_creative_ids: list[str],
        harvest_job_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_ad_assets.create_ad_dna_card_version(
                conn,
                workspace_id=self.workspace_id,
                card_id=card_id,
                brand_kit_id=brand_kit_id,
                brand_kit_version=brand_kit_version,
                card=card,
                source_creative_ids=source_creative_ids,
                harvest_job_id=harvest_job_id,
                model=model,
            )
        )

    def link_pregenerated_assets(
        self, *, card_id: str, card_version: int, links: list[JsonObject]
    ) -> list[str]:
        return self._bridge._run(
            lambda conn: design_ad_assets.link_pregenerated_assets(
                conn,
                workspace_id=self.workspace_id,
                card_id=card_id,
                card_version=card_version,
                links=links,
            )
        )

    # --- reads ---------------------------------------------------------------------------

    def list_creatives(
        self, *, harvest_job_id: Optional[str] = None, limit: int = 50
    ) -> list[JsonObject]:
        return self._bridge._run(
            lambda conn: design_ad_assets.list_ad_creatives(
                conn,
                workspace_id=self.workspace_id,
                harvest_job_id=harvest_job_id,
                limit=limit,
            )
        )

    def get_card(self, card_id: str, version: int) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_ad_assets.get_ad_dna_card(
                conn, workspace_id=self.workspace_id, card_id=card_id, version=version
            )
        )

    def latest_card(
        self, *, brand_kit_id: Optional[str] = None, card_id: Optional[str] = None
    ) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_ad_assets.latest_ad_dna_card(
                conn,
                workspace_id=self.workspace_id,
                brand_kit_id=brand_kit_id,
                card_id=card_id,
            )
        )

    def card_for_job(self, *, harvest_job_id: str) -> Optional[JsonObject]:
        """The card THIS job already published, if any — the W-B1 re-drive probe."""
        return self._bridge._run(
            lambda conn: design_ad_assets.ad_dna_card_for_harvest_job(
                conn, workspace_id=self.workspace_id, harvest_job_id=harvest_job_id
            )
        )

    def list_pregenerated(self, *, card_id: str, card_version: int) -> list[JsonObject]:
        return self._bridge._run(
            lambda conn: design_ad_assets.list_pregenerated_assets(
                conn,
                workspace_id=self.workspace_id,
                card_id=card_id,
                card_version=card_version,
            )
        )
