"""One contextual page owner over display_block, with atomic dependency checks.

Ordinary readers revalidate citations and membership before serving stored text. A failed or
outdated draft never becomes current, and refreshing one project cannot replace another's page.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.display.blocks import LiveBlock, compose_display_block
from clue_api.arv2.display.recipes import OPTIONAL_SECTION_KEYS, Page, read_recipes
from clue_api.arv2.quality_page_inputs import PageInputs, page_inputs
from clue_api.arv2.quality_policy import advisory_research
from clue_api.arv2.research_operations import fingerprint
from clue_obs import get_logger
from clue_research.claimstore.quality import eligible_sql, inspectable_sql
from clue_research.compliance import WorkspacePolicy
from clue_research.compliance.display import research_display_allowed
from clue_storage import (
    StorageBackend,
    artifact_key,
    content_address,
    record_artifact,
    retain_artifact,
)

log = get_logger("arv2.quality.pages")


class CitedSentence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    text: str = Field(min_length=1, max_length=4000)
    claim_ids: tuple[UUID, ...] = Field(default=(), max_length=30, alias="claimIds")
    kind: Literal["fact", "inference", "quote", "qualified", "gap"] = "fact"
    qualifications: tuple[str, ...] = Field(default=(), max_length=20)


class CitedItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    h2: str = Field(min_length=1, max_length=180)
    body: tuple[CitedSentence, ...] = Field(min_length=1, max_length=20)
    contact_ids: tuple[UUID, ...] = Field(default=(), max_length=10, alias="contactIds")
    # Outreach snippets are withheld until the relationship and use gates have cleared.
    send_line: CitedSentence | None = Field(default=None, alias="sendLine")


class PageSectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=100)
    intro: tuple[CitedSentence, ...] = Field(default=(), max_length=30)
    items: tuple[CitedItem, ...] = Field(default=(), max_length=30)
    gaps: tuple[str, ...] = Field(default=(), max_length=30)

    def sentences(self) -> tuple[CitedSentence, ...]:
        return (
            *self.intro,
            *(s for i in self.items for s in i.body),
            *(i.send_line for i in self.items if i.send_line is not None),
        )


class PageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    page: Page
    expected_dependency_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sections: tuple[PageSectionDraft, ...] = Field(min_length=1, max_length=30)
    gaps: tuple[str, ...] = Field(default=(), max_length=50)


async def _validate_sections(
    conn: AsyncConnection,
    scope: JobScope,
    inputs: PageInputs,
    draft: PageDraft,
    *,
    complete: bool = True,
) -> tuple[dict[UUID, dict[str, Any]], dict[UUID, dict[str, Any]]]:
    recipes = await read_recipes(conn, draft.page, workspace_id=scope.workspace_id)
    keys = {r.section_key for r in recipes}
    given = [s.key for s in draft.sections]
    advisory = advisory_research(scope)
    if not advisory and (
        len(set(given)) != len(given)
        or not set(given) <= keys
        or (complete and not keys - OPTIONAL_SECTION_KEYS <= set(given))
    ):
        raise ValueError(
            "a page draft must cover every recipe section once, including explicit gaps"
        )
    ids = {
        id
        for section in draft.sections
        for sentence in section.sentences()
        for id in sentence.claim_ids
    }
    rows = (
        (
            await conn.execute(
                text(f"""SELECT c.*, q.conclusion AS quality,
        {eligible_sql("c")} AS applicable, {inspectable_sql("c")} AS inspectable FROM claim c
        JOIN claim_quality_current q ON q.claim_id=c.id
        WHERE c.workspace_id=:ws AND c.id=ANY(:ids) AND c.entity_id=ANY(:subjects)
          AND (:advisory OR c.superseded_by IS NULL)
          AND (q.context_id IS NULL OR q.context_id=:context)"""),
                {
                    "ws": scope.workspace_id,
                    "ids": sorted(ids),
                    "subjects": list(inputs.subjects),
                    "context": inputs.generation.context_id,
                    "advisory": advisory,
                },
            )
        )
        .mappings()
        .all()
        if ids
        else []
    )
    claims = {r["id"]: dict(r) for r in rows}
    if not advisory and claims.keys() != ids:
        raise ValueError("page cites an unavailable claim or another project/subject")
    members = {m.contact_id: m for m in inputs.members}
    people_ids = {id for s in draft.sections for i in s.items for id in i.contact_ids}
    people = (
        (
            await conn.execute(
                text(
                    "SELECT id,full_name FROM contact_entity "
                    "WHERE workspace_id=:ws AND id=ANY(:ids) AND merged_into IS NULL"
                ),
                {"ws": scope.workspace_id, "ids": list(people_ids)},
            )
        )
        .mappings()
        .all()
        if people_ids
        else []
    )
    people_map = {r["id"]: dict(r) for r in people}
    if advisory:
        return claims, {id: p for id, p in people_map.items() if id in inputs.subjects}
    if people_map.keys() != people_ids or any(
        id not in members or members[id].state == "excluded" for id in people_ids
    ):
        raise ValueError("page names someone outside this contextual committee")
    policy = WorkspacePolicy.model_validate(inputs.manifest["display_policy"])
    for section in draft.sections:
        recipe = next(r for r in recipes if r.section_key == section.key)
        for sentence in section.sentences():
            if sentence.kind != "gap" and not sentence.claim_ids:
                raise ValueError("every factual or inferred sentence needs claim support")
            if (
                sentence.kind in ("qualified", "gap")
                and sentence.claim_ids
                and not sentence.qualifications
            ):
                raise ValueError("qualified findings must retain explicit qualifications")
            for id in sentence.claim_ids:
                claim = claims[id]
                markers = claim["write_markers"] or {}
                if (
                    claim["entity_type"] == "contact"
                    and (
                        claim["entity_id"] not in members
                        or members[claim["entity_id"]].state != "supported"
                    )
                    and sentence.kind not in ("qualified", "gap")
                ):
                    raise ValueError("person findings require qualified committee membership")
                if claim["quality"] == "invalid" or (
                    not claim["applicable"] and sentence.kind not in ("qualified", "gap")
                ):
                    raise ValueError(
                        "invalid or unresolved claims cannot become factual page prose"
                    )
                if not claim["inspectable"] or not research_display_allowed(
                    entity_type=claim["entity_type"],
                    use_class=claim["use_class"],
                    outreach_safe=claim["outreach_safe"],
                    policy=policy,
                    restricted=recipe.restricted or sentence.kind in ("qualified", "gap"),
                ):
                    raise ValueError("page support is unavailable for presentation")
                if claim["field_key"] == "account.open_requisitions":
                    from clue_api.arv2.quality_hiring import current_hiring_state

                    values = claim["value_json"]
                    if (
                        isinstance(values, list)
                        and any(
                            isinstance(v, dict) and current_hiring_state(v) != "open"
                            for v in values
                        )
                        and sentence.kind not in ("qualified", "gap")
                    ):
                        raise ValueError(
                            "closed, historical or undated hiring must remain qualified"
                        )
                if sentence.kind == "quote" and (
                    (
                        claim["entity_type"] == "contact"
                        and claim["source_key"] == "research:transcript"
                        and (markers.get("media") or {}).get("attribution") != "evidence_backed"
                    )
                    or markers.get("claim_kind") not in ("observation", "attributed_statement")
                    or claim["source_key"] not in ("research:web_snapshot", "research:transcript")
                    or not claim["evidence_span"]
                    or sentence.text not in claim["evidence_span"]
                ):
                    raise ValueError(
                        "primary quotes must be exact original evidence, not report excerpts"
                    )
                if markers.get("claim_kind") == "inference" and sentence.kind not in (
                    "inference",
                    "gap",
                    "qualified",
                ):
                    raise ValueError("inferred meaning must remain labelled as inference")
        for item in section.items:
            if any(members[id].state != "supported" for id in item.contact_ids) and any(
                sentence.kind not in ("qualified", "gap") for sentence in item.body
            ):
                raise ValueError("provisional committee findings must remain qualified")
            if item.send_line and (
                not item.send_line.claim_ids
                or item.send_line.kind not in ("fact", "inference")
                or not item.contact_ids
                or any(not members[id].outreach_eligible for id in item.contact_ids)
                or any(not claims[id]["outreach_safe"] for id in item.send_line.claim_ids)
            ):
                raise ValueError("outreach requires supported membership and allowed claims")
    return claims, people_map


def _body(
    section: PageSectionDraft,
    people: dict[UUID, dict[str, Any]],
    gaps: tuple[str, ...],
    account_id: UUID,
) -> dict[str, Any]:
    items = []
    for ordinal, item in enumerate(section.items):
        body = item.model_dump(mode="json", by_alias=True, exclude={"contact_ids", "send_line"})
        body.update(id=f"{section.key}-{ordinal}", priority=2, newSinceLastVisit=False)
        body["contactRefs"] = [
            {"accountId": str(account_id), "contactId": str(id), "name": people[id]["full_name"]}
            for id in item.contact_ids
            if id in people
        ]
        if item.send_line:
            # Exactly the served ``ResearchSendLine`` fields: the read validates strictly, and the
            # sentence's ``kind``/``qualifications`` (already checked above) are not part of it.
            body["sendLine"] = {
                "channel": "email",
                "text": item.send_line.text,
                "claimIds": [str(claim_id) for claim_id in item.send_line.claim_ids],
            }
        items.append(body)
    return {
        "intro": [s.model_dump(mode="json", by_alias=True) for s in section.intro],
        "items": items,
        "_quality_draft": section.model_dump(mode="json"),
        "gaps": [*section.gaps, *gaps],
        "checks": {"quality_validated": True},
    }


async def publish_page(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    *,
    context_id: UUID,
    execution_id: UUID,
    model: str,
    draft: PageDraft,
    complete: bool = True,
) -> tuple[UUID, ...]:
    inputs = await page_inputs(conn, scope, context_id=context_id, page=draft.page, lock=True)
    if not advisory_research(scope) and inputs.sha256 != draft.expected_dependency_sha256:
        raise ValueError(
            "stale_page_inputs: reread page inputs and correct the draft before publishing"
        )
    claims, people = await _validate_sections(conn, scope, inputs, draft, complete=complete)
    raw = draft.model_dump_json(by_alias=True).encode()
    sha = content_address(raw)
    key = artifact_key(scope.workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=scope.workspace_id,
        content_sha256=sha,
        media_type="application/json",
        size_bytes=len(raw),
    )
    await storage.put(key, raw, media_type="application/json")
    parent_keys = {r["artifact_key"] for r in claims.values() if r["artifact_key"]}
    for parent in sorted(parent_keys):
        await conn.execute(
            text(
                "INSERT INTO artifact_derivation(workspace_id,parent_key,child_key) "
                "VALUES(:ws,:parent,:child) ON CONFLICT DO NOTHING"
            ),
            {"ws": scope.workspace_id, "parent": parent, "child": key},
        )
    subject = scope.person_subject_id or scope.account_id
    params = {
        "ws": scope.workspace_id,
        "project": scope.project_id,
        "context": context_id,
        "generation": inputs.generation.generation_id,
        "subject": subject,
        "kind": "contact" if scope.person_subject_id else "account",
        "page": draft.page,
    }
    for entity in {subject, scope.account_id, *(r["entity_id"] for r in claims.values())}:
        await conn.execute(
            text(
                "INSERT INTO agent_artifact_subject "
                "(workspace_id,artifact_key,subject_entity_id,binding_kind) "
                "VALUES(:ws,:key,:entity,'derived') "
                "ON CONFLICT DO NOTHING"
            ),
            {"ws": scope.workspace_id, "key": key, "entity": entity},
        )
    await conn.execute(
        text(
            "INSERT INTO agent_artifact_project(workspace_id,project_id,artifact_key,binding_kind) "
            "VALUES(:ws,:project,:key,'research_page') ON CONFLICT DO NOTHING"
        ),
        {**params, "key": key},
    )
    await retain_artifact(
        conn,
        workspace_id=scope.workspace_id,
        storage_key=key,
        reference_kind="research_page",
        reference_id=f"{execution_id}:{draft.page}:{sha}",
    )
    ids = []
    # Same validated bytes under the same dependencies replay to the same retained rows.
    for section in draft.sections:
        id = uuid5(NAMESPACE_URL, f"research-page:{execution_id}:{sha}:{section.key}")
        existing = (
            await conn.execute(
                text(
                    "SELECT display_block_id,superseded_at FROM display_block "
                    "WHERE display_block_id=:id AND workspace_id=:ws"
                ),
                {"id": id, "ws": scope.workspace_id},
            )
        ).first()
        if existing:
            if existing.superseded_at is not None:
                raise ValueError("page draft was superseded; reread current inputs")
            ids.append(id)
            continue
        await conn.execute(
            text("""UPDATE display_block SET superseded_at=now()
            WHERE workspace_id=:ws AND project_id=:project AND context_id=:context
              AND subject_kind=:kind AND subject_id=:subject AND page=:page
              AND section_key=:section AND superseded_at IS NULL"""),
            {**params, "section": section.key},
        )
        await conn.execute(
            text("""INSERT INTO display_block(display_block_id,workspace_id,project_id,
            context_id,generation_id,subject_kind,subject_id,page,section_key,body_json,cited_claim_ids,
            model,prompt_version,recipe_version,dependency_manifest,output_artifact_key,execution_id)
            VALUES(:id,:ws,:project,:context,:generation,:kind,:subject,:page,:section,
            CAST(:body AS jsonb),
            :claims,:model,'research-quality-pages-v1',1,
            CAST(:manifest AS jsonb),:key,:execution)"""),
            {
                **params,
                "id": id,
                "section": section.key,
                "body": json.dumps(_body(section, people, draft.gaps, scope.account_id)),
                "claims": sorted({id for s in section.sentences() for id in s.claim_ids}),
                "model": model,
                "manifest": json.dumps(
                    section_dependencies(inputs.manifest, section, scope), default=str
                ),
                "key": key,
                "execution": execution_id,
            },
        )
        ids.append(id)
    await conn.execute(
        text("""INSERT INTO arv2_research_page_current
        (workspace_id,project_id,context_id,subject_kind,subject_id,page,generation_id,dependency_sha256)
        VALUES(:ws,:project,:context,:kind,:subject,:page,:generation,:sha)
        ON CONFLICT(workspace_id,project_id,context_id,subject_kind,subject_id,page)
        DO UPDATE SET generation_id=EXCLUDED.generation_id,
          dependency_sha256=EXCLUDED.dependency_sha256,
          updated_at=now()"""),
        {**params, "sha": inputs.sha256},
    )
    log.info(
        "arv2.quality.page_published",
        workspace_id=scope.workspace_id,
        context_id=str(context_id),
        generation_id=str(inputs.generation.generation_id),
        execution_id=str(execution_id),
        job_id=str(scope.job_id),
        page=draft.page,
        sections=len(ids),
    )
    return tuple(ids)


async def read_page(
    conn: AsyncConnection,
    scope: JobScope,
    *,
    context_id: UUID,
    page: Page,
) -> dict[str, Any]:
    """Pure projection. New evidence marks refresh; rejected support suppresses text immediately."""
    inputs = await page_inputs(conn, scope, context_id=context_id, page=page)
    recipes = await read_recipes(conn, page, workspace_id=scope.workspace_id)
    rows = (
        (
            await conn.execute(
                text("""SELECT b.* FROM display_block b
        JOIN artifact a ON a.storage_key=b.output_artifact_key AND a.workspace_id=b.workspace_id
        JOIN arv2_research_page_current p ON p.workspace_id=b.workspace_id
          AND p.project_id=b.project_id AND p.context_id=b.context_id
          AND p.subject_kind=b.subject_kind AND p.subject_id=b.subject_id
          AND p.page=b.page AND p.generation_id=b.generation_id
        WHERE b.workspace_id=:ws AND b.project_id=:project AND b.context_id=:context
          AND b.generation_id=:generation AND b.subject_id=:subject AND b.page=:page
          AND b.superseded_at IS NULL AND a.erased_at IS NULL AND NOT a.privacy_erased
          AND (a.expires_at IS NULL OR a.expires_at>now())"""),
                {
                    "ws": scope.workspace_id,
                    "project": scope.project_id,
                    "context": context_id,
                    "generation": inputs.generation.generation_id,
                    "subject": scope.person_subject_id or scope.account_id,
                    "page": page,
                },
            )
        )
        .mappings()
        .all()
    )
    live, gaps, stale = {}, [], []
    section_titles = {recipe.section_key: recipe.h1 for recipe in recipes}
    for row in rows:
        body = dict(row["body_json"])
        try:
            section = PageSectionDraft.model_validate(body.pop("_quality_draft"))
            draft = PageDraft(
                page=page, expected_dependency_sha256=inputs.sha256, sections=(section,)
            )
            await _validate_sections(conn, scope, inputs, draft, complete=False)
        except (KeyError, ValueError):
            stale.append(row["section_key"])
            title = section_titles.get(row["section_key"], "Research")
            gaps.append(f"{title}: supporting evidence needs review; refresh pending")
            continue
        stored_manifest = row["dependency_manifest"]
        expected_manifest = section_dependencies(
            inputs.manifest,
            section,
            scope,
            force=stored_manifest.get("contract") == "research-section-dependencies-v1",
        )
        # Older owner pages stored the full input inventory. Compare their actual citations
        # using the same projection; an unrelated new claim does not invalidate this section.
        if stored_manifest.get("contract") == "research-quality-pages-v1":
            stored_manifest = section_dependencies(stored_manifest, section, scope)
        if fingerprint(stored_manifest) != fingerprint(expected_manifest):
            stale.append(row["section_key"])
        gaps.extend(body.get("gaps", []))
        live[row["section_key"]] = LiveBlock(
            str(row["display_block_id"]),
            row["section_key"],
            body,
            tuple(str(id) for id in row["cited_claim_ids"]),
            row["model"],
            row["prompt_version"],
            row["recipe_version"],
            row["generated_at"],
        )
    block = compose_display_block(page, recipes, live)
    # Quality pages own every section, including legacy shared-section recipes. No fallback to
    # an unscoped contact page or another project's narrative is permitted.
    for section in block["sections"]:
        stored = live.get(section["key"])
        if stored:
            section.update(
                intro=stored.body_json.get("intro", []), items=stored.body_json.get("items", [])
            )
            section["empty"] = not section["intro"] and not section["items"]
            section["gaps"] = stored.body_json.get("gaps", [])
        section["pending"] = stored is None or section["key"] in stale
        if stored is None and section["key"] in OPTIONAL_SECTION_KEYS:
            section["pending"] = section["key"] in stale
            section["emptyMessage"] = "No additional research findings have been published yet."
    shared_ready: set[str] = set()
    shared_cited: list[str] = []
    from clue_api.arv2.quality_owned_narrative import owns_narrative

    if owns_narrative(scope) and page == "insights" and not scope.person_subject_id:
        from clue_api.arv2.quality_shared_narrative import shared_sections

        shared_ready, shared_stale, shared_cited = await shared_sections(
            conn, scope, context_id, inputs.generation.generation_id, block
        )
        stale.extend(sorted(shared_stale))
    missing = {r.section_key for r in recipes} - live.keys() - shared_ready - OPTIONAL_SECTION_KEYS
    state = inputs.generation.state
    quality = {
        "projectId": scope.project_id,
        "contextId": str(context_id),
        "generationId": str(inputs.generation.generation_id),
        "qualityState": state,
        "refreshPending": bool(stale or missing),
        "gaps": list(dict.fromkeys(gaps)),
        "contexts": [],
    }
    # Founder ruling 2026-09-29: only the designed sections are served, restricted as their
    # recipes say. A research finding no section cites goes into this page's Miscellaneous.
    finding_ids: tuple[str, ...] = ()
    miscellaneous = next((s for s in block["sections"] if s["key"] == "miscellaneous"), None)
    if miscellaneous is not None:
        from clue_api.arv2.quality_presentation import uncovered_findings

        # A finding cited on any of this subject's pages (the overview too) is already shown.
        cited_elsewhere = (
            await conn.execute(
                text("""SELECT DISTINCT unnest(b.cited_claim_ids)::text FROM display_block b
        WHERE b.workspace_id=:ws AND b.project_id=:project AND b.context_id=:context
          AND b.generation_id=:generation AND b.subject_id=:subject
          AND b.superseded_at IS NULL"""),
                {
                    "ws": scope.workspace_id,
                    "project": scope.project_id,
                    "context": context_id,
                    "generation": inputs.generation.generation_id,
                    "subject": scope.person_subject_id or scope.account_id,
                },
            )
        ).scalars()
        cited = (
            {str(id) for b in live.values() for id in b.cited_claim_ids}
            | {str(id) for id in shared_cited}
            | set(cited_elsewhere)
        )
        extra = await uncovered_findings(
            conn,
            scope,
            inputs,
            subject_id=scope.person_subject_id or scope.account_id,
            cited=cited,
        )
        if extra:
            miscellaneous["items"] = [*miscellaneous.get("items", []), *extra]
            miscellaneous["empty"] = False
            miscellaneous["pending"] = False
            miscellaneous.pop("emptyMessage", None)
            finding_ids = tuple(item["body"][0]["claimIds"][0] for item in extra)
    block["researchQuality"] = quality
    return {
        "display_block": block,
        "research_quality": quality,
        "cited_claim_ids": tuple(
            dict.fromkeys(
                [
                    *(id for b in live.values() for id in b.cited_claim_ids),
                    *shared_cited,
                    *finding_ids,
                ]
            )
        ),
        "stale": tuple(stale),
        "pending": tuple(sorted(missing)),
        "generated": (),
        "degraded_reason": None,
    }


def section_dependencies(
    manifest: dict[str, Any], section: PageSectionDraft, scope: JobScope, *, force: bool = False
) -> dict[str, Any]:
    """Owner narratives depend on cited evidence, not every concurrent generation output."""
    from clue_api.arv2.quality_owned_narrative import owns_narrative

    if not force and not owns_narrative(scope):
        return manifest
    cited = {str(id) for s in section.sentences() for id in s.claim_ids}
    people = {str(id) for i in section.items for id in i.contact_ids}
    return {
        **{
            k: v
            for k, v in manifest.items()
            if k not in ("input_revision", "claim_versions", "membership", "recipes", "contract")
        },
        "contract": "research-section-dependencies-v1",
        "claim_versions": [v for v in manifest["claim_versions"] if v[0] in cited],
        "membership": [m for m in manifest["membership"] if str(m["contact_id"]) in people],
        "recipes": [r for r in manifest["recipes"] if r["section_key"] == section.key],
    }
