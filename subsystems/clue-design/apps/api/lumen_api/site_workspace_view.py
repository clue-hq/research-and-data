"""Everything one site turn reads, built from the database (Lane B, B2).

The runtime never reads the database (`lumen_agent/config.py`'s rule), so this module — on the
design API side, in the turn's worker thread — reads the stored kit (resolved by the executor),
the released clones, the workspace's agent sections and the library assets the site already uses,
the account's research and the claims it cites (through the platform's governed reads), the
project's pinned instructions and decisions, and the target account's logos, and hands the
runtime one by-value `SiteTurnInputs`. The seller's pinned files are written by the runtime
itself through the same platform reads (`write_seller_knowledge`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from clue_design.storage import SOURCE_KEY_ASSET
from py_lumen_obs import get_logger
from sqlalchemy import text

from .agent_cloned_sections import DurableAgentClonedSectionRegistry
from .database import NotFoundError
from .fragments import FragmentRefused, read_web_fragment
from .site_brand import (
    _record_digest, asset_store_file, captured_image_descriptions, clone_from_fragment, site_brand_data,
)
from .site_kit_cli import build_site_catalog

logger = get_logger("lumen_api.site_workspace_view")

#: read_cited_claims@1 takes at most 200 ids (Contract 5).
CITED_CLAIMS_CHUNK = 200
_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")


def research_account_id(bundle: Mapping[str, Any], document_id: str) -> str | None:
    """The research account this document was born for: its artifact's `account_id`."""

    artifacts = [item for item in bundle.get("artifacts") or [] if isinstance(item, dict)]
    for item in artifacts:
        if str(item.get("document_id") or "") == document_id and item.get("account_id"):
            return str(item["account_id"])
    named = [item for item in artifacts if item.get("account_id")]
    return str(named[0]["account_id"]) if len(artifacts) == 1 and named else None


def brief_text(bundle: Mapping[str, Any]) -> str:
    """brief.md: the delegation brief, then this artifact's line (the spike's `run_agent.py:139`)."""

    brief = str(bundle.get("brief") or "")
    artifact = bundle.get("artifact")
    return brief + ("\n\nTHIS ARTIFACT: " + json.dumps(artifact) if isinstance(artifact, dict) else "")


def read_research_pages(reads: Any, account_entity_id: str) -> tuple[list[dict], list[dict], dict[str, str]]:
    """The account's overview and insights pages, every block; a page not written is an error."""

    from lumen_agent.site.workspace import read_research

    pages: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    for section in ("overview", "insights"):
        try:
            pages[section] = read_research(reads, account_entity_id, section)
        except Exception as error:  # noqa: BLE001 - a page not written yet is a fact, not a crash
            pages[section], errors[section] = [], str(error) or type(error).__name__
    return pages["overview"], pages["insights"], errors


def cited_claims(reads: Any, account_entity_id: str, sections: Sequence[dict]) -> tuple[list[dict], frozenset[str]]:
    """The served claims the research cites, and the cited ids held back by a real rule.

    Fail-closed: a cited read that fails holds every cited id, so no statement whose claim could
    not be checked reaches the research files (statements with no citation stay).
    """

    from lumen_agent.site.workspace import cited_claim_ids, held_claim_ids

    ids = cited_claim_ids(list(sections))
    claims: list[dict] = []
    dispositions: dict[str, str] = {}
    try:
        for start in range(0, len(ids), CITED_CLAIMS_CHUNK):
            answer = reads.read_cited_claims(entity_id=account_entity_id, claim_ids=ids[start : start + CITED_CLAIMS_CHUNK])
            claims += list(answer.get("claims") or [])
            dispositions.update(answer.get("dispositions") or {})
    except Exception:  # noqa: BLE001 - logged; the research keeps only uncited statements
        logger.warning("site_turn.cited_claims_unavailable", account_entity_id=account_entity_id, exc_info=True)
        return [], frozenset(ids)
    return claims, frozenset(held_claim_ids(dispositions))


def project_files_from(reads: Any) -> list[dict]:
    """The opening turn's pinned instructions.md and decisions.md, as plain markdown."""

    try:
        context = reads.project_design_context()
    except Exception:  # noqa: BLE001 - unavailable context is no context
        return []
    if context.get("status") != "available":
        return []
    return [
        {"path": str(item.get("path") or ""), "body_text": str(item.get("body_text") or "")}
        for item in context.get("files") or []
        if isinstance(item, dict)
    ]


def fetch_account_logos(blobs: Any, account_card: Mapping[str, Any] | None, *, fetcher: Any = None, cache: Any = None) -> list:
    """The target account's logo family (the spike's `fetch_account_logo`), stored as design blobs:
    the recommended logos, then every other real logo found, each named /asset-store/<sha256>."""

    from lumen_agent.site.inputs import AccountLogo

    card = account_card or {}
    domain = card.get("domain")
    if not domain:
        return []
    if fetcher is None:
        from lumen_agent.tools.logo_fetch import fetch_logo_family as fetcher
    try:
        outcome = fetcher(str(domain), company_name=card.get("name"), cache=cache)
    except Exception:  # noqa: BLE001 - a blocked site or a vendor miss: the header goes without a logo
        logger.info("site_turn.account_logo_unavailable", domain=str(domain), exc_info=True)
        return []
    logos = []
    for prepared, alternative in [*((p, False) for p in outcome.prepared), *((a, True) for a in outcome.alternatives)]:
        blobs.register(prepared.body, media_type=prepared.content_type, source_key=SOURCE_KEY_ASSET)
        digest = hashlib.sha256(prepared.body).hexdigest()
        logos.append(AccountLogo(
            cell=prepared.cell, file=asset_store_file(digest), content_type=prepared.content_type,
            label=prepared.label if alternative else None, alternative=alternative,
        ))
    return logos


def list_site_clones(blobs: Any, cache_dir: Any) -> list[dict]:
    """The released clones the catalog offers: approved, lineage-resolved (a superseded row gives way
    to its repair), degraded ones listed WITH their note. Every role is offered, the seller's nav and
    footer bands and the composed ABM campaign shells included (founder answer, open question 2 (a),
    2026-10-12): which ones fit a page is the agent's judgement, guided by its skill."""

    registry = DurableAgentClonedSectionRegistry(blobs=blobs, cache_dir=cache_dir)
    clones: list[dict] = []
    for section in registry.list_sections().get("sections") or []:
        if section.get("superseded_by"):
            continue
        try:
            loaded = read_web_fragment(blobs.storage, workspace_id=blobs.workspace_id, fragment_id=str(section["fragment_id"]))
        except (NotFoundError, FragmentRefused):
            continue
        clones.append(clone_from_fragment(section, loaded))
    return clones


def pinned_site_clones(site: Mapping[str, Any], blobs: Any, *, listed: set[str]) -> list[dict]:
    """The sections this site's pages already use that the catalog no longer offers (founder ruling
    Q5, 2026-10-12): a section superseded by a repair, retired, or not yet approved. Each is loaded by
    id whatever its status and marked ``in_catalog: False``, so the page still draws, saves and
    reaches publish (which applies its own rule) while the agent is not offered it anew. A section
    that no longer exists is left out, so the save check and publish refuse it honestly."""

    pinned: list[dict] = []
    seen: set[str] = set(listed)
    for page in (site.get("pages") or {}).values():
        for item in (page or {}).get("content") or []:
            if item.get("type") != "ClonedSection":
                continue
            fragment_id = str((item.get("props") or {}).get("fragmentId") or "")
            if not fragment_id or fragment_id in seen:
                continue
            seen.add(fragment_id)
            try:
                loaded = read_web_fragment(blobs.storage, workspace_id=blobs.workspace_id, fragment_id=fragment_id)
            except (NotFoundError, FragmentRefused):
                continue
            # A web_fragment row names its page, position and brokenness in its own columns
            # (provenance, degraded/degraded_reason); the registry's one row shaper reads them.
            section = DurableAgentClonedSectionRegistry._section_row(loaded.row)
            pinned.append({**clone_from_fragment(section, loaded), "in_catalog": False})
    return pinned


def site_sections_for_turn(store: Any, blobs: Any, site: Mapping[str, Any]) -> dict:
    """The sections a turn may place: each name the document pins at its pinned digest, plus the
    newest section of every other name in the workspace (sections are per workspace)."""

    from lumen_agent.site.inputs import SiteSection

    pinned = {str(name): str(digest) for name, digest in (site.get("agent_sections") or {}).items()}
    pinned_rows = {row["digest"]: row for row in store.get_site_sections(list(pinned.values()))}
    chosen = {name: pinned_rows[digest] for name, digest in pinned.items() if digest in pinned_rows}
    for row in store.list_latest_site_sections():
        chosen.setdefault(str(row["name"]), row)
    sections = {}
    for name, row in chosen.items():
        try:
            module_js, css = read_section_bytes(blobs, row)
        except NotFoundError:
            continue
        sections[name] = SiteSection(name=name, digest=row["digest"], props_schema=row["props_schema"], module_js=module_js, css=css)
    return sections


def load_site_section_modules(repo: Any, blobs: Any, agent_sections: Mapping[str, str]) -> list:
    """Lane A's ``site_section_loader`` (Contract 4): the modules a site pins, from this workspace's
    store. A pin this workspace does not hold, held under another name, or whose files are gone
    refuses with ``render.section_module_missing`` (a save answers site.invalid, a publish refuses);
    Lane A's ``pinned_modules`` then checks each module's bytes hash to its pin."""

    from .site_render import SECTION_MODULE_MISSING, SectionModule, SiteRenderError

    pins = {str(name): str(digest) for name, digest in agent_sections.items()}
    rows = {row["digest"]: row for row in repo.get_site_sections(list(pins.values()))}
    modules = []
    for name, digest in pins.items():
        row = rows.get(digest)
        if row is None or row["name"] != name:
            raise SiteRenderError(SECTION_MODULE_MISSING, f"agent section {name} has no stored module {digest[:12]}")
        try:
            module_js, css = read_section_bytes(blobs, row)
        except NotFoundError as error:
            raise SiteRenderError(SECTION_MODULE_MISSING, f"agent section {name}'s stored files are gone") from error
        modules.append(SectionModule(name=name, digest=digest, module_js=module_js, css=css, props_schema=row["props_schema"]))
    return modules


def read_section_bytes(blobs: Any, row: Mapping[str, Any]) -> tuple[str, str]:
    """A recorded section's compiled module and CSS (raises NotFoundError when either is gone).
    The one read of section files: the turn's sections here, Lane A's loader in Task 15."""

    return blobs.read(row["module_sha256"]).decode("utf-8"), blobs.read(row["css_sha256"]).decode("utf-8")


def site_brand_for(
    site: Mapping[str, Any],
    blobs: Any,
    *,
    cache_dir: Any,
    brand_kit: Mapping[str, Any] | None,
    kit_assets: Mapping[str, Any] | None,
    font_spec: Mapping[str, Any] | None,
    library_assets: Mapping[str, Any],
) -> dict:
    """The site's BrandData: its pinned kit, the released clones plus every section its pages already
    use (marked out of the catalog), and the library images given."""

    kit_ref = (site.get("theme") or {}).get("brand_kit")
    listed = list_site_clones(blobs, cache_dir)
    pinned = pinned_site_clones(site, blobs, listed={str(clone["id"]) for clone in listed})
    return site_brand_data(
        slug=str((kit_ref or {}).get("id") or blobs.workspace_id),
        kit=dict(brand_kit or {}),
        kit_assets=dict(kit_assets or {}),
        font_faces=list((font_spec or {}).get("faces") or []),
        clones=listed + pinned,
        library_assets=dict(library_assets),
        captured_image_descriptions=captured_image_descriptions(listed + pinned, workspace_id=blobs.workspace_id),
    )


def site_brand_loader_for(cache_dir_for: Any) -> Any:
    """Lane A's ``site_brand_loader(repo, blobs, document) -> BrandData`` (its write validation,
    render and publish call it). ``cache_dir_for(workspace_id)`` names the engine cache the clone
    registry reads. Library images are left out: a save validates the images the workspace holds
    as ``siteImages`` (contract conflict 2), so only the turn needs them in the brand."""

    def load(repo: Any, blobs: Any, document: Mapping[str, Any]) -> dict:
        from .main import resolve_web_turn_brand_kit

        site = document["scene"]
        brand_kit, _source, kit_assets, font_spec = resolve_web_turn_brand_kit(site, blobs)
        return site_brand_for(
            site, blobs, cache_dir=cache_dir_for(blobs.workspace_id), brand_kit=brand_kit,
            kit_assets=kit_assets, font_spec=font_spec, library_assets={},
        )

    return load


def referenced_digests(site: Mapping[str, Any]) -> set[str]:
    return set(_ASSET_REF.findall(json.dumps(site)))


def referenced_library_assets(asset_library: Mapping[str, Mapping[str, Any]], digests: set[str]) -> dict:
    """The workspace library assets the site already shows (generated images included)."""

    return {
        asset_id: entry
        for asset_id, entry in asset_library.items()
        if _record_digest(entry.get("record") or {}) in digests
    }


#: Images and logos only: a font or a document is never a section image.
_SEARCHABLE_KINDS = frozenset({"raster_image", "vector"})


def search_candidates(kit_assets: Mapping[str, Any] | None, asset_library: Mapping[str, Any] | None) -> dict:
    """search_assets' inventory: the kit's assets, then the workspace library, images only."""

    candidates: dict[str, dict] = {}
    for origin, manifest in (("brand_kit", kit_assets or {}), ("library", asset_library or {})):
        for asset_id, entry in manifest.items():
            record = entry.get("record") or {}
            if record.get("kind") in _SEARCHABLE_KINDS and record.get("status", "ready") != "archived":
                candidates.setdefault(asset_id, {**entry, "origin": origin})
    return candidates


def seller_name(store: Any, kit_ref: Mapping[str, Any] | None, kit: Mapping[str, Any] | None) -> str:
    """The seller's name for brand/brand.md: the brand the kit belongs to, else the kit's own name."""

    if isinstance(kit_ref, Mapping) and kit_ref.get("id") and kit_ref.get("version") is not None:
        async def read(conn: Any) -> str | None:
            row = (await conn.execute(
                text("SELECT b.name FROM design_brand_kit k JOIN brand b ON b.brand_id = k.brand_id "
                     "WHERE k.workspace_id = :w AND k.brand_kit_id = :id AND k.version = :v"),
                {"w": store.workspace_id, "id": str(kit_ref["id"]), "v": int(kit_ref["version"])},
            )).first()
            return None if row is None else str(row.name)

        try:
            name = store._bridge._run(read)
        except Exception:  # noqa: BLE001 - the kit's own name is the honest fallback
            name = None
        if name:
            return name
    return str((kit or {}).get("name") or "the seller")


def build_site_turn_inputs(
    *,
    document: Mapping[str, Any],
    store: Any,
    blobs: Any,
    cache_dir: Any,
    platform_reads: Any,
    account_card: Mapping[str, Any] | None,
    delegation_bundle: Mapping[str, Any] | None,
    brand_kit: Mapping[str, Any] | None,
    kit_assets: Mapping[str, Any] | None,
    font_spec: Mapping[str, Any] | None,
    asset_library: Mapping[str, Any] | None,
    assets: Any = None,
    sections: Any = None,
    site_versions: Any = None,
    renderer: Any = None,
    logo_cache: Any = None,
):
    """One site turn's inputs. Raises only on a broken toolchain (the catalog CLI)."""

    from lumen_agent.site.inputs import SiteTurnInputs

    site = document["scene"]
    document_id = str(document["id"])
    kit_ref = (site.get("theme") or {}).get("brand_kit")
    brand = site_brand_for(
        site, blobs, cache_dir=cache_dir, brand_kit=brand_kit, kit_assets=kit_assets, font_spec=font_spec,
        library_assets=referenced_library_assets(asset_library or {}, referenced_digests(site)),
    )
    seller = seller_name(store, kit_ref, brand_kit)
    bundle = delegation_bundle or {}
    card = account_card or {}
    overview: list[dict] = []
    insights: list[dict] = []
    claims: list[dict] = []
    held: frozenset[str] = frozenset()
    account_entity_id = research_account_id(bundle, document_id)
    if platform_reads is not None and account_entity_id:
        overview, insights, _errors = read_research_pages(platform_reads, account_entity_id)
        claims, held = cited_claims(platform_reads, account_entity_id, overview + insights)
    artifact = bundle.get("artifact") if isinstance(bundle.get("artifact"), dict) else {}
    candidates = search_candidates(kit_assets, asset_library)
    if candidates:
        from .asset_embeddings import load_workspace_embeddings

        embeddings = load_workspace_embeddings(blobs.workspace_id)
    else:
        embeddings = {}
    return SiteTurnInputs(
        document_id=document_id,
        workspace_id=blobs.workspace_id,
        brief=brief_text(bundle),
        account_name=str(card.get("name") or artifact.get("title") or "the account"),
        seller=seller,
        brand=brand,
        catalog=build_site_catalog(brand, seller),
        overview=overview,
        insights=insights,
        claims=claims,
        held_claim_ids=held,
        project_files=project_files_from(platform_reads) if platform_reads is not None else [],
        account_logos=fetch_account_logos(blobs, card, cache=logo_cache),
        agent_sections=site_sections_for_turn(store, blobs, site),
        asset_candidates=candidates,
        asset_embeddings=embeddings,
        platform_reads=platform_reads,
        assets=assets,
        sections=sections,
        site_versions=site_versions,
        renderer=renderer,
    )
