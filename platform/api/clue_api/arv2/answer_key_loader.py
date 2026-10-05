"""Load the two ARV2 answer-key files into one real database (D1's exit gate).

The mapping is pure (:mod:`clue_api.arv2.answer_key`); this module is the side of it that touches
the store. It creates the spine the rows need to exist under (workspace → brand → product →
project), the account and contact entities every claim keys on, the project run and run lineage the
project lens reads through, the transcript artifacts the media-quoted claims cite, every claim
through the lenient write gate, the ARV2 research run and job that make the Zafran account read as
*researched*, the activity feed the detail rail renders, and — so the research lane has something
to launch against — the project's confirmed product set (version 1) plus the two stand-in
brand-knowledge documents (a confirmed ``icp-definition`` and its ``audience-persona``) registered
the way Track O's ICP gate will.

It is deliberately **one-shot per database**: a second load would double every claim, so the first
thing it does is look for its own run id and refuse. There is no update path — the answer key is a
fixture, and a fresh database is how you reload it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_catalog import (
    ARV2_ACCOUNT_PROFILE_REF,
    arv2_account_profile_sha256,
)
from clue_api.arv2.account_research_store import (
    JobStatus,
    RunRow,
    begin_job,
    create_job,
    create_run,
    finish_job,
    read_run,
    refresh_run_status,
)
from clue_api.arv2.answer_key import (
    ANSWER_KEY_NAMESPACE,  # research-run ids share the run ids' uuid5 namespace
    PEOPLE_RUN_ID,
    WORK_EMAIL_KEY,
    ZAFRAN_ANSWER_KEY,
    ZAFRAN_MANIFEST,
    AnswerKeyManifest,
    MappedRows,
    RowDraft,
    map_people_rows,
    map_zafran_rows,
)
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter, WriteReceipt
from clue_api.arv2.onboarding_documents import KnowledgeDocument, render_markdown
from clue_api.arv2_wiring import register_arv2_wiring
from clue_api.composition import RESEARCH_PACK_LOADERS
from clue_auth.store import create_platform_user, get_platform_user
from clue_config import Settings
from clue_core import (
    AccountStatus,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ProjectPhase,
    ResearchMode,
    RunId,
    UseClass,
)
from clue_research.claimstore.run_lineage import record_run_lineage
from clue_research.durable.project_run import ensure_project_run
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_research.membership import ensure_project_account
from clue_spine import (
    confirm_project_product_set,
    create_brand,
    create_product,
    create_project,
    create_workspace,
    get_workspace,
)
from clue_storage.artifacts import record_artifact
from clue_storage.fs import FsStorage
from clue_storage.protocol import artifact_key, content_address

#: Where the two answer-key files and the Zafran transcripts live, relative to ``context_root``.
ZAFRAN_DIR = "arv2-one-account-aiark"
PEOPLE_DIR = "arv2-person-depth"
#: Where the hand-written stand-in ICP and persona documents live, relative to ``context_root``.
KNOWLEDGE_DIR = "arv2-answer-key-knowledge"

#: The synthetic human the loader confirms the product set and the ICP as. It is a real
#: ``platform_user`` row (the product-set table's FK demands one) whose name says what it is.
ANSWER_KEY_USER_ID = "usr_arv2_answer_key"
#: ``project_product.gate_id`` is not a foreign key (clue_spine sits below the gate table), so the
#: loader names the gate it never opened deterministically and honestly: no gate row exists.
PRODUCT_SET_GATE_ID = uuid.uuid5(ANSWER_KEY_NAMESPACE, "arv2-answer-key:product-set-gate:v1")

#: The one researched account — the other three were only named by the run.
ZAFRAN_DOMAIN = "zafran.io"

_TRANSCRIPT_MEDIA_TYPE = "text/markdown"
_TRANSCRIPT_SOURCE_KEY = "arv2:answer_key:transcript"
_DOCUMENT_SOURCE_KEY = "arv2:answer_key:knowledge_document"
_ICP_KIND = "icp-definition"
_ORIGIN = "arv2-answer-key-loader"
_BUDGET_REF = "answer-key"
_PERSONA_KEY = "contact.persona"
_ROLE_KEY = "contact.role_on_committee"
_TITLE_KEY = "contact.current_title"
#: The Zafran committee read drops a member with no role claim, and the run wrote a role row for
#: only two of its five people — so the loader derives the missing three from the persona the same
#: lookup recorded, and says so in the claim's own markers.
_DERIVED_ROLE_RATIONALE = (
    "role derived from the committee persona recorded by the name-scoped AI Ark lookup"
)
_DERIVED_ROLE_SOURCE_KEY = "ai_ark"

# -- the ARV2 research run and job the answer key stands for --------------------------------------

#: The deterministic ids of the one run and the one job the answer key is. Both hang off the
#: load's uuid5 namespace, so the repair below writes exactly the rows a fresh load writes.
ARV2_RESEARCH_RUN_ID = uuid.uuid5(ANSWER_KEY_NAMESPACE, "arv2-research-run:zafran")
ARV2_RESEARCH_JOB_ID = uuid.uuid5(ANSWER_KEY_NAMESPACE, "arv2-research-job:zafran")
#: What the run says it was: the effort, the cap and the steer a human would have signed off on.
ARV2_EFFORT = "full"
ARV2_COMMITTEE_CAP = 5
ARV2_DIRECTIVE = "D1 answer key — Zafran (2026-09-02 proof-of-concept run)"
#: The ICP the run pins. The 2026-09-02 run predates the ICP gate, so there is no confirmed
#: ``icp-definition`` it was launched against — the run pins a small stand-in document of its own,
#: named for what it is, rather than borrowing an ICP the run never saw.
ARV2_STANDIN_ICP_KEY = "answer-key-standin"
ARV2_STANDIN_ICP_VERSION = 1
#: The product selection a launch pins. The answer key confirms exactly one product set, version 1.
ARV2_PRODUCT_SELECTION_VERSION = 1
_STANDIN_ICP_SOURCE_KEY = "arv2:answer_key:standin_icp"
#: Fixed bytes — no clock, no ids — so the artifact is content-addressed to the same sha on every
#: database, and the repair path lands on the same key the load did.
_STANDIN_ICP_BODY = """# ARV2 answer key — stand-in ICP

The 2026-09-02 Zafran proof-of-concept run was driven by hand, before the ICP gate existed. It
was not launched against a confirmed `icp-definition` document, so this file stands in for the one
a real launch pins: it exists so the answer key's research run can record *which ICP it researched
against* honestly, rather than pointing at a document the run never read.

Audience: the ABM buyers of a security vendor's marketing team — the people the Zafran run went
looking for. The real thing is authored by Track O's synthesis agent and confirmed by a human.
"""


class AlreadyLoaded(RuntimeError):
    """The answer key is already in this database; loading again would duplicate every claim."""


@dataclass(frozen=True)
class LoadReport:
    """What one load wrote — the operator's receipt, and the test's assertion surface."""

    workspace_id: str
    project_id: str
    run_id: str
    accounts: dict[str, str]  # domain -> account_entity_id
    contacts: dict[str, str]  # linkedin_url -> contact_entity_id
    claims_written: int
    registered_fields: list[str]
    markers: dict[str, int]  # marker name -> count
    skips: list[dict[str, str]]  # {"source_row_id", "reason"}
    artifacts: list[str]  # artifact keys
    product_selection_version: int
    documents: dict[str, str]  # document path -> brand_knowledge_document id
    research: ResearchRowsReport  # the ARV2 run and job the Zafran account reads as researched


async def load_answer_key(
    conn: AsyncConnection,
    *,
    storage: FsStorage,
    context_root: Path,
    settings: Settings,
) -> LoadReport:
    """Load both answer-key files into ``conn``'s database, inside the caller's transaction."""
    manifest = ZAFRAN_MANIFEST
    await _refuse_if_loaded(conn, manifest.run_id)

    zafran = map_zafran_rows(_read_json(context_root / ZAFRAN_DIR / "claims_zafran.json"))
    people = map_people_rows(
        _read_json(context_root / PEOPLE_DIR / "claims_people.json"),
        _read_json(context_root / PEOPLE_DIR / "roster.json"),
    )
    zafran_drafts = (*zafran.drafts, *_derived_role_drafts(zafran))

    brand_id, product_id = await _ensure_spine(conn, manifest)
    await _load_packs(conn)
    accounts, contacts = await _entities(conn, manifest)
    await ensure_project_run(
        conn,
        project_run_id=manifest.project_run_id,
        project_id=manifest.project_id,
        workspace_id=manifest.workspace_id,
        icp_key=manifest.icp_key,
        icp_version=1,
        phase=ProjectPhase.DEEP,
    )
    selection_version = await _confirm_product_set(conn, manifest, product_id)
    documents = await _knowledge_documents(
        conn,
        storage,
        context_root,
        manifest,
        brand_id=brand_id,
        product_id=product_id,
        selection_version=selection_version,
    )
    for run_id, kind in ((manifest.run_id, "entity_research"), (PEOPLE_RUN_ID, "contact_research")):
        await record_run_lineage(
            conn,
            run_id=run_id,
            workspace_id=manifest.workspace_id,
            kind=kind,
            project_id=manifest.project_id,
            project_run_id=manifest.project_run_id,
        )

    media_keys = await _media_artifacts(conn, storage, context_root, manifest)
    subjects = _subject_index(accounts, contacts)
    writer = LenientClaimWriter(lenient=settings.claim_write_lenient)
    zafran_written = await _write_claims(
        conn, writer, zafran_drafts, subjects, manifest.run_id, media_keys, manifest.workspace_id
    )
    people_written = await _write_claims(
        conn, writer, people.drafts, subjects, PEOPLE_RUN_ID, media_keys, manifest.workspace_id
    )
    written = [*zafran_written, *people_written]

    committee = [contacts[url] for url in _zafran_committee_urls(manifest)]
    research = await _research_rows(
        conn,
        storage=storage,
        manifest=manifest,
        brand_id=brand_id,
        account_id=accounts[ZAFRAN_DOMAIN],
        claims_written=len(zafran_written),
    )
    await _activity(conn, manifest, accounts, facts=len(zafran_written), committee=len(committee))

    markers: dict[str, int] = {}
    for _, receipt in written:
        for name in receipt.markers:
            markers[name] = markers.get(name, 0) + 1
    return LoadReport(
        workspace_id=manifest.workspace_id,
        project_id=manifest.project_id,
        run_id=str(manifest.run_id),
        accounts={domain: str(value) for domain, value in accounts.items()},
        contacts={url: str(value) for url, value in contacts.items()},
        claims_written=len(written),
        registered_fields=sorted(
            {receipt.field_key for _, receipt in written if receipt.registered_field}
        ),
        markers=dict(sorted(markers.items())),
        skips=[
            {"source_row_id": skip.source_row_id, "reason": skip.reason}
            for skip in (*zafran.skips, *people.skips)
        ],
        artifacts=sorted(media_keys.values()),
        product_selection_version=selection_version,
        documents=documents,
        research=research,
    )


# -- step 1: the one-shot guard -----------------------------------------------------------------


async def _refuse_if_loaded(conn: AsyncConnection, run_id: RunId) -> None:
    found = (
        await conn.execute(
            text("SELECT 1 FROM claim WHERE run_id = :run_id LIMIT 1"), {"run_id": run_id}
        )
    ).first()
    if found is not None:
        raise AlreadyLoaded(
            f"answer key already loaded into this database (run {run_id}); use a fresh database"
        )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# -- step 2: the spine --------------------------------------------------------------------------


async def _ensure_spine(conn: AsyncConnection, manifest: AnswerKeyManifest) -> tuple[str, str]:
    """Create workspace → brand → product → project, and return ``(brand_id, product_id)``.

    Only the workspace is get-or-create: it is the row a partially-set-up dev database is most
    likely to already have. Everything below it is created outright, because this loader owns the
    whole ``ws_arv2_answer_key`` tenant and a collision there means the database is not the fresh
    one the answer key needs.
    """
    if await get_workspace(conn, manifest.workspace_id) is None:
        await create_workspace(
            conn, name=manifest.workspace_name, workspace_id=manifest.workspace_id
        )
    brand = await create_brand(conn, workspace_id=manifest.workspace_id, name=manifest.brand_name)
    product = await create_product(
        conn,
        brand_id=brand.brand_id,
        workspace_id=manifest.workspace_id,
        name=manifest.product_name,
    )
    await create_project(
        conn,
        workspace_id=manifest.workspace_id,
        brand_id=brand.brand_id,
        name=manifest.project_name,
        project_id=manifest.project_id,
        status="active",
    )
    return str(brand.brand_id), str(product.product_id)


async def _confirm_product_set(
    conn: AsyncConnection, manifest: AnswerKeyManifest, product_id: str
) -> int:
    """Confirm the project's product set as version 1, so a launch has a version to pin.

    Master plan §5.1 / rulings P1–P2: a research run pins ``product_selection_version``; without a
    confirmed set there is nothing to pin and the R2 launch tool would have to refuse. The spine
    function wants the confirming human, so the loader's synthetic user is created on first use.
    """
    if await get_platform_user(conn, ANSWER_KEY_USER_ID) is None:
        await create_platform_user(
            conn, user_id=ANSWER_KEY_USER_ID, display_name="ARV2 answer key (loader)"
        )
    confirmed = await confirm_project_product_set(
        conn,
        workspace_id=manifest.workspace_id,
        project_id=manifest.project_id,
        product_ids=[product_id],
        gate_id=PRODUCT_SET_GATE_ID,
        confirmed_by_user_id=ANSWER_KEY_USER_ID,
    )
    if confirmed is None:
        raise RuntimeError(
            "the answer-key product set could not be confirmed against its own project — the "
            "spine rows this loader just created do not agree with each other"
        )
    return confirmed.selection_version


# -- step 3: the field registry -----------------------------------------------------------------


async def _load_packs(conn: AsyncConnection) -> None:
    """Seed every registered field pack, ARV2's included, through the composition-root list.

    The list is the production registry (PF-7): reaching for the individual pack loaders would
    both duplicate their order and cross the ARV2 import boundary.
    """
    register_arv2_wiring()
    for loader in RESEARCH_PACK_LOADERS:
        await loader(conn)


# -- step 4: the entities -----------------------------------------------------------------------


async def _entities(
    conn: AsyncConnection, manifest: AnswerKeyManifest
) -> tuple[dict[str, EntityId], dict[str, EntityId]]:
    """Create the five accounts (with project membership) and the twelve people under them."""
    accounts: dict[str, EntityId] = {}
    for spec in manifest.accounts:
        account_id = await insert_account_entity(
            conn,
            canonical_name=spec.name,
            primary_domain=spec.domain,
            status=AccountStatus.CANDIDATE,
            workspace_id=manifest.workspace_id,
        )
        await ensure_project_account(
            conn,
            workspace_id=manifest.workspace_id,
            project_id=manifest.project_id,
            account_entity_id=account_id,
            added_via="manual",
        )
        accounts[spec.domain] = account_id

    contacts: dict[str, EntityId] = {}
    for person in manifest.people:
        contacts[person.linkedin_url] = await insert_contact_entity(
            conn,
            account_entity_id=accounts[person.company_domain],
            full_name=person.name,
            linkedin_url=person.linkedin_url,
        )
    return accounts, contacts


def _subject_index(
    accounts: Mapping[str, EntityId], contacts: Mapping[str, EntityId]
) -> dict[str, EntityId]:
    """``RowDraft.subject`` → entity id, for both subject spellings in one map."""
    index = {f"account:{domain}": value for domain, value in accounts.items()}
    index.update({f"contact:{url}": value for url, value in contacts.items()})
    return index


def _zafran_committee_urls(manifest: AnswerKeyManifest) -> tuple[str, ...]:
    return tuple(
        person.linkedin_url for person in manifest.people if person.company_domain == ZAFRAN_DOMAIN
    )


# -- the three derived committee-role claims ----------------------------------------------------


def _derived_role_drafts(zafran: MappedRows) -> tuple[RowDraft, ...]:
    """One ``contact.role_on_committee`` row per Zafran person who has a persona but no role.

    The governed committee read requires both claims and drops a member carrying only one, so
    without these three the answer key's five-person committee reads as two. The value is not
    invented: it restates the persona the same provider row recorded, with the person's own title
    as the rationale and the originating row id in ``markers`` so the derivation is traceable.
    """
    personas = {draft.subject: draft for draft in zafran.drafts if draft.field_key == _PERSONA_KEY}
    roles = {draft.subject for draft in zafran.drafts if draft.field_key == _ROLE_KEY}
    titles: dict[str, RowDraft] = {}
    for draft in zafran.drafts:  # file order — the first title a subject was given wins
        if draft.field_key == _TITLE_KEY:
            titles.setdefault(draft.subject, draft)

    derived: list[RowDraft] = []
    for subject, persona in personas.items():
        if subject in roles:
            continue
        title = titles[subject].value_json
        derived.append(
            RowDraft(
                subject=subject,
                entity_type=EntityType.CONTACT,
                field_key=_ROLE_KEY,
                value_json={
                    "role": persona.value_json,
                    "rationale": f"{title} — {_DERIVED_ROLE_RATIONALE}",
                    "plausible": True,
                },
                extraction_method=ExtractionMethod.API,
                research_mode=ResearchMode.CONTACT_PROFILING,
                source_url=None,
                source_key=_DERIVED_ROLE_SOURCE_KEY,
                evidence_span=None,
                observed_at=persona.observed_at,
                confidence=persona.confidence,
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PROFESSIONAL_PUBLIC,
                signal_priority=3,
                outreach_safe=True,
                media_url=None,
                field_description=None,
                markers={
                    "derived_role_from_persona": persona.source_row_id,
                    "answer_key": ZAFRAN_ANSWER_KEY,
                },
                source_row_id=f"derived-role:{persona.source_row_id}",
            )
        )
    return tuple(derived)


# -- step 7: the transcript artifacts -----------------------------------------------------------


async def _media_artifacts(
    conn: AsyncConnection,
    storage: FsStorage,
    context_root: Path,
    manifest: AnswerKeyManifest,
) -> dict[str, str]:
    """Record and store one artifact per transcribed media item; return ``{media_url: key}``."""
    keys: dict[str, str] = {}
    for spec in manifest.media:
        data = (context_root / ZAFRAN_DIR / "transcripts" / spec.transcript_file).read_bytes()
        sha = content_address(data)
        key = artifact_key(manifest.workspace_id, sha)
        await record_artifact(
            conn,
            storage_key=key,
            workspace_id=manifest.workspace_id,
            content_sha256=sha,
            media_type=_TRANSCRIPT_MEDIA_TYPE,
            size_bytes=len(data),
            source_key=_TRANSCRIPT_SOURCE_KEY,
            source_url=spec.media_url,
        )
        await storage.put(key, data, media_type=_TRANSCRIPT_MEDIA_TYPE)
        keys[spec.media_url] = key
    return keys


# -- step 7b: the stand-in brand-knowledge documents ---------------------------------------------


def _split_front_matter(markdown: str) -> tuple[dict[str, Any], str]:
    """``---\n<yaml>\n---\n\n<body>`` → ``(front matter, body)``; a file without one is refused."""
    if not markdown.startswith("---\n"):
        raise ValueError("a knowledge document starts with a YAML front-matter block")
    end = markdown.find("\n---\n", 4)
    if end < 0:
        raise ValueError("a knowledge document's front-matter block is never closed")
    front = yaml.safe_load(markdown[4:end])
    if not isinstance(front, dict):
        raise ValueError("a knowledge document's front matter is a mapping")
    return front, markdown[end + len("\n---\n") :].lstrip("\n")


async def _knowledge_documents(
    conn: AsyncConnection,
    storage: FsStorage,
    context_root: Path,
    manifest: AnswerKeyManifest,
    *,
    brand_id: str,
    product_id: str,
    selection_version: int,
) -> dict[str, str]:
    """Register the stand-in ICP and persona documents; return ``{path: document_id}``.

    This is the shape Track O's ICP gate (O6) will produce for real: one
    ``brand_knowledge_document`` row per document, its rendered markdown stored as a
    content-addressed artifact, the ICP row
    ``confirmed`` with the confirmation-only front-matter fields (`ARV2-ONBOARDING-PLAN.md` §6.1)
    stamped at confirmation time — here, at load time, because the brand id, product id, project
    and selection version only exist once the spine has been created. The persona document is
    ``ready``: it is authored per ICP version, never confirmed. When O3's document helpers land,
    they own this write and the loader calls them.
    """
    confirmed_at = datetime.now(UTC)
    written: dict[str, str] = {}
    for spec in manifest.documents:
        source = (context_root / KNOWLEDGE_DIR / spec.file).read_text(encoding="utf-8")
        front, body = _split_front_matter(source)
        if front.get("kind") != spec.kind:
            raise ValueError(
                f"{spec.file} declares kind {front.get('kind')!r}, expected {spec.kind!r}"
            )
        if front.get("icp_key") != manifest.icp_key:
            raise ValueError(
                f"{spec.file} names ICP {front.get('icp_key')!r}, expected {manifest.icp_key!r}"
            )
        front["brand_id"] = brand_id
        if spec.kind == _ICP_KIND:
            front["product_ids"] = [product_id]
            front["confirmed_by"] = ANSWER_KEY_USER_ID
            front["confirmed_at"] = confirmed_at.isoformat()
            front["confirmed_for_project_id"] = manifest.project_id
            front["product_selection_version"] = selection_version
            status = "confirmed"
        else:
            status = "ready"
        folder = spec.path.split("/", 1)[0]
        rendered = render_markdown(
            KnowledgeDocument(
                kind=spec.kind,
                folder=folder,
                path=spec.path,
                front_matter=front,
                body=body,
                cost=None,
            )
        ).encode("utf-8")
        sha = content_address(rendered)
        key = artifact_key(manifest.workspace_id, sha)
        await record_artifact(
            conn,
            storage_key=key,
            workspace_id=manifest.workspace_id,
            content_sha256=sha,
            media_type=_TRANSCRIPT_MEDIA_TYPE,
            size_bytes=len(rendered),
            source_key=_DOCUMENT_SOURCE_KEY,
        )
        await storage.put(key, rendered, media_type=_TRANSCRIPT_MEDIA_TYPE)
        document_id = uuid.uuid5(ANSWER_KEY_NAMESPACE, f"arv2-answer-key:document:{spec.path}")
        await conn.execute(
            text(
                """
                INSERT INTO brand_knowledge_document
                    (document_id, workspace_id, brand_id, folder, path, kind, version, status,
                     artifact_key, artifact_sha256)
                VALUES
                    (:document_id, :workspace_id, :brand_id, :folder, :path, :kind, 1, :status,
                     :artifact_key, :artifact_sha256)
                """
            ),
            {
                "document_id": document_id,
                "workspace_id": manifest.workspace_id,
                "brand_id": brand_id,
                "folder": folder,
                "path": spec.path,
                "kind": spec.kind,
                "status": status,
                "artifact_key": key,
                "artifact_sha256": sha,
            },
        )
        written[spec.path] = str(document_id)
    return written


# -- step 8: the claims -------------------------------------------------------------------------


async def _write_claims(
    conn: AsyncConnection,
    writer: LenientClaimWriter,
    drafts: Sequence[RowDraft],
    subjects: Mapping[str, EntityId],
    run_id: RunId,
    media_keys: Mapping[str, str],
    workspace_id: str,
) -> list[tuple[RowDraft, WriteReceipt]]:
    written: list[tuple[RowDraft, WriteReceipt]] = []
    for draft in drafts:
        receipt = await writer.write(
            conn,
            ClaimDraft(
                entity_id=subjects[draft.subject],
                entity_type=draft.entity_type,
                field_key=draft.field_key,
                value_json=draft.value_json,
                extraction_method=draft.extraction_method,
                run_id=run_id,
                research_mode=draft.research_mode,
                workspace_id=workspace_id,
                source_url=draft.source_url,
                source_key=draft.source_key,
                evidence_span=draft.evidence_span,
                observed_at=draft.observed_at,
                confidence=draft.confidence,
                identity_binding=draft.identity_binding,
                use_class=draft.use_class,
                signal_priority=draft.signal_priority,
                outreach_safe=draft.outreach_safe,
                artifact_key=media_keys.get(draft.media_url) if draft.media_url else None,
                field_description=draft.field_description,
                markers=draft.markers,
            ),
        )
        written.append((draft, receipt))
    return written


# -- step 9: the ARV2 research run and job -------------------------------------------------------


def _sha256_json(payload: Mapping[str, Any]) -> str:
    """A canonical digest of one JSON payload. ``default=str`` so a uuid in it is hashable."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ResearchRowsReport:
    """What one pass over the ARV2 run/job rows did — the operator's receipt and the assertions.

    ``runs_created`` / ``jobs_created`` are 0 or 1: the ids are deterministic, so a second pass
    creates nothing and says so, rather than either failing or quietly writing a second run.
    """

    run_id: str
    job_id: str
    account_entity_id: str
    claims_written: int
    runs_created: int
    jobs_created: int
    status: str


_ZAFRAN_ACCOUNT = text(
    "SELECT id FROM account_entity WHERE workspace_id = :workspace_id AND primary_domain = :domain"
)
_PROJECT_BRAND = text(
    "SELECT brand_id FROM project WHERE workspace_id = :workspace_id AND project_id = :project_id"
)
#: How many facts the Zafran run is standing behind, counted from the store rather than remembered
#: — so the repair reports the same number on an already-loaded database that the load reports on a
#: fresh one, and a later supersession (the D4-b email repair) does not inflate it.
_ZAFRAN_LIVE_CLAIMS = text(
    "SELECT count(*) FROM claim WHERE workspace_id = :workspace_id AND run_id = :run_id "
    "AND superseded_by IS NULL"
)


async def _standin_icp(
    conn: AsyncConnection, storage: FsStorage, manifest: AnswerKeyManifest
) -> tuple[str, str]:
    """Store the stand-in ICP the run pins, and return ``(artifact_key, sha256)``.

    Written exactly the way the transcripts are — ``record_artifact`` then ``storage.put`` — so the
    run's ICP pin resolves to real bytes a reader can fetch, not to a key nothing backs.
    """
    data = _STANDIN_ICP_BODY.encode("utf-8")
    sha = content_address(data)
    key = artifact_key(manifest.workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=manifest.workspace_id,
        content_sha256=sha,
        media_type=_TRANSCRIPT_MEDIA_TYPE,
        size_bytes=len(data),
        source_key=_STANDIN_ICP_SOURCE_KEY,
    )
    await storage.put(key, data, media_type=_TRANSCRIPT_MEDIA_TYPE)
    return key, sha


async def _research_rows(
    conn: AsyncConnection,
    *,
    storage: FsStorage,
    manifest: AnswerKeyManifest,
    brand_id: str,
    account_id: EntityId,
    claims_written: int,
) -> ResearchRowsReport:
    """Record the ARV2 run and job that make the Zafran account read as *researched*.

    Founder ruling 2026-09-09 — **ARV2's own rows are the only truth**. The answer key is one
    account's finished research, so what it writes is one :func:`create_run` and one
    :func:`create_job`, driven to ``completed`` through the same store transitions R2's driver
    uses (``begin_job`` → ``finish_job`` → ``refresh_run_status``). It writes nothing to the old
    lane's ``entity_research_*`` tables; those are dead data on this path.

    The other three accounts get no job at all. "Never researched" is a fact about a missing row,
    and inventing a ``not_started`` job for an account nobody launched would say the opposite.

    Idempotent on the deterministic ids: a second pass inserts nothing, drives nothing, and
    reports the run's stored status.
    """
    icp_key, icp_sha = await _standin_icp(conn, storage, manifest)
    profile_sha = arv2_account_profile_sha256()
    request: dict[str, Any] = {
        # The answer key itself is the request: the manifest names the workspace, the project, the
        # run and every subject, and the pins below are what a launch of it would have signed off.
        "answer_key_manifest": asdict(manifest),
        "account_entity_id": str(account_id),
        "icp_artifact_key": icp_key,
        "icp_artifact_sha256": icp_sha,
        "icp_key": ARV2_STANDIN_ICP_KEY,
        "icp_version": ARV2_STANDIN_ICP_VERSION,
        "product_selection_version": ARV2_PRODUCT_SELECTION_VERSION,
        "effort": ARV2_EFFORT,
        "committee_cap": ARV2_COMMITTEE_CAP,
        "directive_text": ARV2_DIRECTIVE,
        "profile_ref": ARV2_ACCOUNT_PROFILE_REF,
        "profile_sha256": profile_sha,
        "requested_by_user_id": _ORIGIN,
    }
    run_created = await create_run(
        conn,
        RunRow(
            run_id=ARV2_RESEARCH_RUN_ID,
            workspace_id=manifest.workspace_id,
            project_id=manifest.project_id,
            brand_id=brand_id,
            project_run_id=uuid.UUID(str(manifest.project_run_id)),
            icp_artifact_key=icp_key,
            icp_artifact_sha256=icp_sha,
            icp_key=ARV2_STANDIN_ICP_KEY,
            icp_version=ARV2_STANDIN_ICP_VERSION,
            product_selection_version=ARV2_PRODUCT_SELECTION_VERSION,
            effort=ARV2_EFFORT,
            committee_cap=ARV2_COMMITTEE_CAP,
            directive_text=ARV2_DIRECTIVE,
            profile_ref=ARV2_ACCOUNT_PROFILE_REF,
            profile_sha256=profile_sha,
            # A free-text column (no ``platform_user`` foreign key), so it names the loader rather
            # than borrowing a human's id for a run no human launched.
            requested_by_user_id=_ORIGIN,
            request_sha256=_sha256_json(request),
        ),
    )
    job_created = await create_job(
        conn,
        job_id=ARV2_RESEARCH_JOB_ID,
        run_id=ARV2_RESEARCH_RUN_ID,
        workspace_id=manifest.workspace_id,
        account_entity_id=uuid.UUID(str(account_id)),
    )
    if job_created:
        begun = await begin_job(conn, job_id=ARV2_RESEARCH_JOB_ID)
        assert begun is not None, "the job row was inserted by this transaction"
        await finish_job(
            conn,
            job_id=ARV2_RESEARCH_JOB_ID,
            attempt=begun.attempt,
            status="completed",
            finalization={"claims_written": claims_written, "source": "answer-key"},
            # The run was driven by hand off-platform, so there is no model or provider spend to
            # attribute to it. Zero is the true number, not a placeholder.
            model_rounds=0,
            tool_calls=0,
            cost_usd=Decimal(0),
            credits=Decimal(0),
            media_seconds=0,
        )
        status: JobStatus | str = await refresh_run_status(conn, run_id=ARV2_RESEARCH_RUN_ID)
    else:
        stored = await read_run(conn, run_id=ARV2_RESEARCH_RUN_ID)
        status = stored.status if stored is not None else "not_started"
    return ResearchRowsReport(
        run_id=str(ARV2_RESEARCH_RUN_ID),
        job_id=str(ARV2_RESEARCH_JOB_ID),
        account_entity_id=str(account_id),
        claims_written=claims_written,
        runs_created=int(run_created),
        jobs_created=int(job_created),
        status=str(status),
    )


async def repair_research_rows(conn: AsyncConnection, *, storage: FsStorage) -> ResearchRowsReport:
    """Give an already-loaded database the ARV2 run and job a fresh load now writes.

    D1 wrote the old lane's terminal ``entity_research_*`` rows instead; every screen has since
    moved to ARV2's own rows (D4-b), so a database loaded before this change shows its researched
    account as *not started*. This writes the missing pair, reading its inputs back out of the
    database rather than re-deriving them — the spine, the entities and the claims are already
    there and are not touched.

    It deliberately leaves the legacy rows alone. They are dead data, not something to migrate:
    nothing reads them any more, and the Phase-6 PR drops the tables outright.
    """
    manifest = ZAFRAN_MANIFEST
    brand_id = (
        await conn.execute(
            _PROJECT_BRAND,
            {"workspace_id": manifest.workspace_id, "project_id": manifest.project_id},
        )
    ).scalar_one_or_none()
    if brand_id is None:
        raise RuntimeError(
            f"project {manifest.project_id!r} does not exist in workspace "
            f"{manifest.workspace_id!r} — this database has no answer key to repair"
        )
    account_id = (
        await conn.execute(
            _ZAFRAN_ACCOUNT,
            {"workspace_id": manifest.workspace_id, "domain": ZAFRAN_DOMAIN},
        )
    ).scalar_one_or_none()
    if account_id is None:
        raise RuntimeError(
            f"workspace {manifest.workspace_id!r} has no {ZAFRAN_DOMAIN} account — this database "
            "has no answer key to repair"
        )
    claims = (
        await conn.execute(
            _ZAFRAN_LIVE_CLAIMS,
            {"workspace_id": manifest.workspace_id, "run_id": manifest.run_id},
        )
    ).scalar_one()
    return await _research_rows(
        conn,
        storage=storage,
        manifest=manifest,
        brand_id=str(brand_id),
        account_id=EntityId(uuid.UUID(str(account_id))),
        claims_written=int(claims),
    )


# -- step 10: the activity feed ------------------------------------------------------------------


_ACTIVITY = text(
    """
    INSERT INTO account_activity_event
        (workspace_id, account_entity_id, kind, actor_kind, text, action, occurred_at, project_id)
    VALUES (:workspace_id, :account_id, :kind, 'clue', :text, :action, :occurred_at, :project_id)
    """
)


async def _activity(
    conn: AsyncConnection,
    manifest: AnswerKeyManifest,
    accounts: Mapping[str, EntityId],
    *,
    facts: int,
    committee: int,
) -> None:
    """Write the feed the detail rail renders (source map §3.8), all ``clue``-authored.

    Zafran gets the full story — created, researched, committee confirmed. The other four accounts
    were only ever named by a run (Probook's research is R2's to do live), so ``created`` is the
    only honest event for them.
    """
    occurred_at = datetime.now(UTC)
    events: list[tuple[EntityId, str, str, str]] = [
        (accounts[ZAFRAN_DOMAIN], "created", "Account created", "added Zafran Security"),
        (accounts[ZAFRAN_DOMAIN], "updated", "Account researched", f"researched {facts} facts"),
        (
            accounts[ZAFRAN_DOMAIN],
            "contacts",
            "Buying committee confirmed",
            f"{committee} people",
        ),
    ]
    events.extend(
        (accounts[spec.domain], "created", "Account created", f"added {spec.name}")
        for spec in manifest.accounts
        if spec.domain != ZAFRAN_DOMAIN
    )
    for index, (account_id, kind, label, action) in enumerate(events):
        await conn.execute(
            _ACTIVITY,
            {
                "workspace_id": manifest.workspace_id,
                "account_id": account_id,
                "kind": kind,
                "text": label,
                "action": action,
                # Staggered so the feed's ``ORDER BY occurred_at`` is the order written here.
                "occurred_at": occurred_at + timedelta(milliseconds=index),
                "project_id": manifest.project_id,
            },
        )


# -- the email repair (ARV2 D4-b task 4) ---------------------------------------------------------

#: The marker a repaired claim carries, so the rewrite is visible in the row itself forever.
EMAIL_REPAIR_MARKER = "email_repair"
EMAIL_REPAIR_VERSION = "d4b"

_BARE_EMAIL_CLAIMS = text(
    """
    SELECT id, entity_id, write_markers->>'source_row_id' AS source_row_id, value_json
    FROM claim
    WHERE workspace_id = :workspace_id
      AND field_key = :field_key
      AND superseded_by IS NULL
      AND jsonb_typeof(value_json) = 'string'
    ORDER BY collected_at, id
    """
)


@dataclass(frozen=True)
class EmailRepairReport:
    """What one ``--repair-emails`` pass did: the operator's receipt and the test's assertions."""

    found: int  # live ``core.work_email`` claims still holding a bare address string
    repaired: int
    skipped: list[dict[str, str]]  # {"claim_id", "reason"} — never silently dropped


async def repair_email_claims(
    conn: AsyncConnection,
    *,
    context_root: Path,
    settings: Settings,
) -> EmailRepairReport:
    """Give the loaded answer key's work-email claims the verdict D4-b's value shape demands.

    D1 wrote each address as a bare string, because that is what the field registry declared then.
    The verdict that grades it was in the answer-key row all along (AI Ark's ``verification``
    block) and is now part of the value, so those rows can be corrected in place — by supersession,
    never by an UPDATE: the old row keeps its provenance and gains a forward pointer.

    Idempotent by construction: it looks for live claims whose value is still a JSON *string*, and
    what it writes is an object. A second pass finds nothing. A claim whose answer-key row cannot
    be found, or whose row carries no verdict, is left exactly as it is and reported as skipped —
    the repair invents no verdict.
    """

    manifest = ZAFRAN_MANIFEST
    drafts = {
        draft.source_row_id: draft
        for draft in map_zafran_rows(
            _read_json(context_root / ZAFRAN_DIR / "claims_zafran.json")
        ).drafts
        if draft.field_key == WORK_EMAIL_KEY
    }
    rows = (
        (
            await conn.execute(
                _BARE_EMAIL_CLAIMS,
                {"workspace_id": manifest.workspace_id, "field_key": WORK_EMAIL_KEY},
            )
        )
        .mappings()
        .all()
    )
    writer = LenientClaimWriter(lenient=settings.claim_write_lenient)
    repaired = 0
    skipped: list[dict[str, str]] = []
    for row in rows:
        claim_id = str(row["id"])
        draft = drafts.get(str(row["source_row_id"]))
        address = row["value_json"]
        if draft is None:
            skipped.append({"claim_id": claim_id, "reason": "no_answer_key_row"})
            continue
        value = draft.value_json
        if not isinstance(value, dict) or value.get("address") != address:
            # Either the answer key has no verdict for this row, or it names a different address
            # than the database holds. Both mean the two disagree about what happened; the claim
            # store is append-only and this is a repair, not a re-research.
            skipped.append({"claim_id": claim_id, "reason": "answer_key_disagrees"})
            continue
        receipt = await writer.write(
            conn,
            ClaimDraft(
                # The provenance is the stored row's own: the subject comes from the claim, and
                # everything else from the draft the loader wrote it from.
                entity_id=EntityId(uuid.UUID(str(row["entity_id"]))),
                entity_type=draft.entity_type,
                field_key=draft.field_key,
                value_json=value,
                extraction_method=draft.extraction_method,
                run_id=manifest.run_id,
                research_mode=draft.research_mode,
                workspace_id=manifest.workspace_id,
                source_url=draft.source_url,
                source_key=draft.source_key,
                evidence_span=draft.evidence_span,
                observed_at=draft.observed_at,
                confidence=draft.confidence,
                identity_binding=draft.identity_binding,
                use_class=draft.use_class,
                signal_priority=draft.signal_priority,
                outreach_safe=draft.outreach_safe,
                field_description=draft.field_description,
                markers={**draft.markers, EMAIL_REPAIR_MARKER: EMAIL_REPAIR_VERSION},
            ),
        )
        # The second half of ``clue_research.claimstore.supersede_claim``; its first half is the
        # lenient writer's own insert, which is the ARV2 lane's single write path into the store.
        await conn.execute(
            text("UPDATE claim SET superseded_by = :new_id WHERE id = :old_id"),
            {"new_id": receipt.claim_id, "old_id": row["id"]},
        )
        repaired += 1
    return EmailRepairReport(found=len(rows), repaired=repaired, skipped=skipped)


__all__ = [
    "ARV2_RESEARCH_JOB_ID",
    "ARV2_RESEARCH_RUN_ID",
    "EMAIL_REPAIR_MARKER",
    "AlreadyLoaded",
    "EmailRepairReport",
    "LoadReport",
    "ResearchRowsReport",
    "load_answer_key",
    "repair_email_claims",
    "repair_research_rows",
]
