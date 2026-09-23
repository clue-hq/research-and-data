"""Deterministic opening research brief from pinned documents and the launch assignment.

No model summarises this input. Structured values and source passages remain verbatim, with
explicit continuation references for longer prose. The account agent still writes Exa's charter.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_catalog import (
    CONTACT_ENRICHMENT_POLICY,
    RESEARCH_PROVIDER_POLICY,
)
from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.quality_context import ResearchContext, read_document
from clue_api.arv2.quality_execution import Allowance
from clue_api.arv2.quality_history import history_page, retain_history
from clue_storage import StorageBackend

_METADATA = frozenset(
    {
        "kind",
        "status",
        "version",
        "brand_id",
        "project_id",
        "product_id",
        "product_ids",
        "provider_run_id",
        "source_document",
        "source_sha256",
        "icp_key",
        "icp_version",
        "persona_version",
        "product_selection_version",
        "confirmed_at",
        "confirmed_by",
        "confirmed_by_user_id",
        "confirmed_for_project_id",
        "confirmation_source",
        "confirmed_from_document_id",
        "confirmation_gate_id",
        "display",
    }
)
_BODY_PREVIEW_CHARS = 6000


def _research_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _research_values(v) for k, v in value.items() if k not in _METADATA}
    if isinstance(value, list):
        return [_research_values(v) for v in value]
    return value


def document_excerpt(raw: str) -> tuple[str, bool]:
    """Keep every structured research instruction; preview prose with a visible continuation."""
    try:
        front, body = parse_front_matter(raw)
    except ValueError:
        front, body = {}, raw
    values = _research_values(front)
    structured = yaml.safe_dump(values, sort_keys=False, allow_unicode=True) if values else ""
    omitted = len(body) > _BODY_PREVIEW_CHARS
    excerpt = body[:_BODY_PREVIEW_CHARS] if omitted else body
    return "\n\n".join(p for p in (structured.strip(), excerpt.strip()) if p), omitted


def render_brief(brief: dict[str, Any], *, provider: bool = False) -> str:
    """Two renderings of the same context; provider text excludes internal storage references."""
    lines = [
        "# Research assignment",
        f"Project: {brief['project']['name']}",
        brief["project"]["description"] or "No project description supplied.",
        brief["assignment"] or "No additional Head-of-ABM directive was supplied.",
        "# Seller and selected products",
        f"Seller: {brief['seller_name']}",
        *[f"- {name}" for name in brief["products"].values()],
        "Keep selected products distinct. Seller capabilities are context for relevance, not "
        "evidence that the target has a problem or uses a product. Pricing, proof points, "
        "integrations and competitors are unspecified unless documented below or in the originals.",
    ]
    groups = (
        ("Seller source material", {"company-overview", "product-research"}),
        ("ICP research lens", {"icp-definition"}),
        ("Persona and responsibility map", {"audience-persona"}),
    )
    for title, kinds in groups:
        lines.append(f"# {title}")
        docs = [d for d in brief["documents"] if d["kind"] in kinds]
        if not docs:
            lines.append("Not supplied in the pinned context.")
        for doc in docs:
            lines += [
                f"## {doc['label']} ({doc.get('scope', 'retained')} document revision "
                f"{doc['version']})",
                doc["excerpt"],
            ]
            if not provider:
                lines.append(f"Complete pinned original: {doc['path']} (SHA-256 {doc['sha256']})")
            if doc["prose_continues"]:
                lines.append(
                    "The prose continues beyond this excerpt. "
                    + (
                        "The researcher may supply further relevant passages in the charter."
                        if provider
                        else "Read the complete original for details needed in your Exa charter."
                    )
                )
    lines += [
        "Treat ICP gates as questions to investigate, not reasons to halt research. "
        "Persona titles describe possible responsibilities, not a proven committee.",
        "# Target context",
        json.dumps(brief["target"], ensure_ascii=False, indent=2, sort_keys=True),
        "# Existing knowledge and open questions",
        "Earlier findings can be stale, disputed or from another context revision. Reuse useful "
        "work and revisit contradictions; do not present it as fresh verification.",
    ]
    for item in brief["known_claims"]:
        value = {
            k: item[k]
            for k in (
                "entity_id",
                "field_key",
                "value_preview",
                "source_url",
                "observed_at",
                "collected_at",
                "assessment",
                "superseded_by",
                "value_continues",
            )
        }
        lines.append(json.dumps(value, ensure_ascii=False, default=str))
        if not provider:
            lines.append(f"Full finding and evidence: {item['path']}")
    lines.append(
        f"Prior findings available: {brief['known_claims_total']}; "
        f"included here: {len(brief['known_claims'])}."
    )
    for item in brief["known_sources"]:
        lines.append(
            f"- {item['kind']} | {item['observed_at']} | "
            f"{item['source_url'] or 'Stored provider source; no public URL'}"
        )
        if not provider:
            lines.append(f"  Original: {item['path']}")
    lines.append(
        f"Prior source records available: {brief['known_sources_total']}; "
        f"listed here: {len(brief['known_sources'])}."
    )
    if not provider:
        lines += [
            "All prior findings: /research/history/claims/0.json",
            "All original research and acquisition gaps: /research/history/sources/0.json",
        ]
    lines += ["# Context gaps", *[f"- {gap}" for gap in brief["gaps"]]]
    if not brief["gaps"]:
        lines.append(
            "No missing document pins recorded; this does not certify research completeness."
        )
    if not provider:
        lines += [
            "# Run scope",
            json.dumps(brief["run_scope"], indent=2, default=str),
            CONTACT_ENRICHMENT_POLICY,
            RESEARCH_PROVIDER_POLICY,
            "Use this brief to decide what matters for this target and to author the Exa charter "
            "and follow-up probes. The provider receives the same seller/ICP/persona research "
            "context automatically; include additional original passages where the excerpts "
            "above omit relevant detail. Preserve uncertainty and surface the findings.",
        ]
    return "\n\n".join(lines)


async def compile_brief(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    scope: JobScope,
    context: ResearchContext,
    context_id: UUID,
    as_of: datetime,
    limits: Allowance,
    media_ceiling_s: int | None,
) -> dict[str, Any]:
    launch = (
        (
            await conn.execute(
                text("""
      SELECT r.directive_text,p.name,p.description FROM arv2_research_run r
      JOIN project p ON p.project_id=r.project_id AND p.workspace_id=r.workspace_id
      WHERE r.run_id=:run AND r.workspace_id=:ws AND r.project_id=:project
    """),
                {"run": scope.run_id, "ws": scope.workspace_id, "project": scope.project_id},
            )
        )
        .mappings()
        .one()
    )
    documents = []
    for doc in context.documents():
        raw = await read_document(conn, storage, workspace_id=scope.workspace_id, pin=doc)
        excerpt, continues = document_excerpt(raw)
        documents.append(
            {
                "kind": doc.kind,
                "label": doc.path,
                "version": doc.document_version,
                "sha256": doc.sha256,
                "path": f"/research/documents/{doc.document_id}/0.json",
                "excerpt": excerpt,
                "prose_continues": continues,
                "scope": "project" if doc.project_id else "brand",
            }
        )
    claims = await history_page(conn, scope, kind="claims", before=as_of)
    sources = await history_page(conn, scope, kind="sources", before=as_of)
    await retain_history(conn, scope, claims["items"] + sources["items"])
    previews = []
    for item in claims["items"]:
        value = json.dumps(item["value_json"], ensure_ascii=False, default=str)
        previews.append(
            {
                **{
                    k: v
                    for k, v in item.items()
                    if k
                    not in (
                        "value_json",
                        "evidence_span",
                        "write_markers",
                        "artifact_key",
                        "rationale_key",
                    )
                },
                "value_preview": value[:1500],
                "value_continues": len(value) > 1500,
            }
        )
    identity = (
        (
            await conn.execute(
                text("""
      SELECT hq_geo,aliases,registry_ids FROM account_entity WHERE id=:id AND workspace_id=:ws
    """),
                {"id": scope.account_id, "ws": scope.workspace_id},
            )
        )
        .mappings()
        .one()
    )
    target: dict[str, Any] = {
        "account": scope.account_name,
        "domain": scope.account_domain,
        "subject_kind": scope.subject_kind,
        "research_date": str(scope.today),
        "known_hq": identity["hq_geo"],
        "known_aliases": identity["aliases"],
        "registry_ids": identity["registry_ids"],
    }
    if scope.person_subject_id:
        target.update(
            person=scope.person_name,
            title=scope.person_title,
            linkedin=scope.person_linkedin_url,
            prior_employment_context=list(scope.employment_history),
        )
    return {
        "version": 1,
        "context_id": str(context_id),
        "as_of": as_of.isoformat(),
        "assignment": launch["directive_text"],
        "project": {"name": launch["name"], "description": launch["description"]},
        "seller_name": context.seller_name,
        "products": context.products,
        "product_selection_version": context.product_selection_version,
        "documents": documents,
        "target": target,
        "gaps": list(context.gaps),
        "known_claims": previews,
        "known_claims_total": claims["total"],
        "known_sources": sources["items"],
        "known_sources_total": sources["total"],
        "run_scope": {
            "effort": scope.effort,
            "committee_cap": scope.committee_cap,
            "limits": asdict(limits),
            "media_ceiling_s": media_ceiling_s,
            "money_budget_mode": "record_only",
        },
    }
