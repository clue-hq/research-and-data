"""The durable target-logo family cache (founder decision #4, 2026-08-31).

Keyed `(workspace_id, exact_host)` -- product hosts remain distinct from parents,
the tool receives a domain and the agent may fetch for companies that are not
accounts (founder ruling 2026-09-02). Workspace-scoped by construction: the
blob store carries the tenant (the `agent_account_logos` rule) and the row
lives under the same workspace, so a cross-tenant read is as unresolvable as
an absent one.

No TTL: the eviction affordance is `force_refresh` on the fetch tool. The
cache is an OPTIMIZATION, never a gate -- every read error degrades to a miss
and every write error is logged and swallowed; the fetch path must never die
on cache trouble.

Custody is PROBED, not assumed. A row can outlive its bytes (a backend whose
root moved, a restore that brought the database back without the object store,
an out-of-band delete), so a hit whose cells are not all `READABLE` is reported
as a MISS -- the whole family, not the surviving cells, because half a 2x2 is
not the family the dispatch asked for. The next dispatch refetches and re-puts,
which is honest and self-healing. The family includes the ALTERNATIVES (the
other real assets found for the company), stored and probed under the same rule.
"""

from __future__ import annotations

from typing import Any

from py_lumen_obs import get_logger

from clue_design.storage import SOURCE_KEY_ASSET

from .design_store import CustodyState, DesignBlobStore

_logger = get_logger("lumen_api.agent_logo_family_cache")

__all__ = ["DurableLogoFamilyCache"]


class DurableLogoFamilyCache:
    """get/put for one workspace. Duck-typed against the prep layer's seam."""

    def __init__(self, *, blobs: DesignBlobStore) -> None:
        self.blobs = blobs
        self.workspace_id = blobs.workspace_id

    # -- keying ------------------------------------------------------------

    @staticmethod
    def _key(site: str) -> str:
        from lumen_ingestion.provider_identity import normalized_host

        return normalized_host(site)

    # -- seam --------------------------------------------------------------

    def get(self, site: str):
        try:
            return self._get(site)
        except Exception:  # noqa: BLE001 - a cache read error is a MISS
            _logger.warning("logo_family_cache.read_failed", exc_info=True)
            return None

    def put(self, site: str, outcome: Any) -> None:
        if not getattr(outcome, "prepared", None):
            return
        try:
            self._put(site, outcome)
        except Exception:  # noqa: BLE001 - a cache write error never fails the turn
            _logger.warning("logo_family_cache.write_failed", exc_info=True)

    # -- implementation ----------------------------------------------------

    def _put(self, site: str, outcome: Any) -> None:
        import hashlib

        from clue_design import logo_family_cache as dal

        from .design_store import DesignStoreBridge

        def entry(prepared) -> dict:
            sha = hashlib.sha256(prepared.body).hexdigest()
            # Content-addressed and idempotent end to end (row before blob), so a re-put of the
            # same mark converges rather than duplicating custody.
            self.blobs.register(
                prepared.body, media_type=prepared.content_type, source_key=SOURCE_KEY_ASSET
            )
            return {
                "sha256": sha,
                "content_type": prepared.content_type,
                "source": prepared.source,
                "origin_url": prepared.source_ref.get("url"),
                "evidence": prepared.evidence,
                "provenance": prepared.provenance,
                "source_ref": prepared.source_ref,
                "label": prepared.label,
                "asset_id": prepared.asset_id,
            }

        cells = {prepared.cell: entry(prepared) for prepared in outcome.prepared}
        # The alternatives are part of the family, so they are stored with it. A list,
        # not a map: several of them can name the same cell.
        alternatives = [
            {**entry(prepared), "cell": prepared.cell}
            for prepared in getattr(outcome, "alternatives", None) or []
        ]
        family = {
            "identity_policy_version": 2,
            "site": outcome.site,
            "company": outcome.company,
            "lockup_completeness": outcome.lockup_completeness,
            "identity": outcome.identity,
            "notes": list(outcome.notes),
            "cells": cells,
            "alternatives": alternatives,
        }
        DesignStoreBridge(self.workspace_id)._run(
            lambda conn: dal.upsert_logo_family(
                conn,
                workspace_id=self.workspace_id,
                registrable_domain=self._key(site),
                family=family,
            )
        )

    def _get(self, site: str):
        from clue_design import logo_family_cache as dal
        from lumen_agent.tools.logo_fetch import LogoFetchOutcome, PreparedLogo

        from .design_store import DesignStoreBridge

        row = DesignStoreBridge(self.workspace_id)._run(
            lambda conn: dal.get_logo_family(
                conn, workspace_id=self.workspace_id, registrable_domain=self._key(site)
            )
        )
        if row is None:
            return None
        family = row["family"]
        # Old entries predate provider identity checks and used parent-domain keys.
        # Treat them as misses without deleting the historic source evidence.
        if (
            family.get("identity_policy_version") != 2
            or self._key(family.get("site", "")) != self._key(site)
        ):
            return None
        cells = family.get("cells") or {}
        if not cells:
            return None
        stored_alternatives = family.get("alternatives") or []
        # Cells AND alternatives: a missing alternative blob is a whole-family miss too,
        # because half a family is not the family the dispatch asked for.
        digests = [c["sha256"] for c in cells.values()]
        digests += [a["sha256"] for a in stored_alternatives]
        states = self.blobs.custody_states(digests)
        if any(states.get(d) is not CustodyState.READABLE for d in digests):
            return None  # any unreadable cell = the WHOLE family is a miss (honest; refetch)

        def restore(name: str, c: dict) -> PreparedLogo:
            return PreparedLogo(
                cell=name,
                source=c["source"],
                asset_id=c["asset_id"],
                label=c["label"],
                body=self.blobs.read(c["sha256"]),
                content_type=c["content_type"],
                provenance=c["provenance"],
                source_ref=c["source_ref"],
                evidence=c["evidence"],
            )

        prepared = [restore(name, c) for name, c in cells.items()]
        alternatives = [restore(a.get("cell") or "unclassified", a) for a in stored_alternatives]
        return LogoFetchOutcome(
            status="ok",
            site=family["site"],
            company=family.get("company"),
            prepared=prepared,
            cells={p.cell: p.source for p in prepared},
            alternatives=alternatives,
            identity=family.get("identity") or {},
            lockup_completeness=family.get("lockup_completeness", "unknown"),
            notes=list(family.get("notes") or []),
        )
