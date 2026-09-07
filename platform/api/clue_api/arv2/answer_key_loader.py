"""Load the two ARV2 answer-key files into one real database (D1's exit gate).

The mapping is pure (:mod:`clue_api.arv2.answer_key`); this module is the side of it that touches
the store. It creates the spine the rows need to exist under (workspace → brand → product →
project), the account and contact entities every claim keys on, the project run and run lineage the
project lens reads through, the transcript artifacts the media-quoted claims cite, every claim
through the lenient write gate, the terminal research run/job/coverage that makes the Zafran
account read as *researched with a five-person committee*, and the activity feed the detail rail
renders.

It is deliberately **one-shot per database**: a second load would double every claim, so the first
thing it does is look for its own run id and refuse. There is no update path — the answer key is a
fixture, and a fresh database is how you reload it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.answer_key import (
    ANSWER_KEY_NAMESPACE,  # research-run ids share the run ids' uuid5 namespace
    PEOPLE_RUN_ID,
    ZAFRAN_MANIFEST,
    AnswerKeyManifest,
    MappedRows,
    RowDraft,
    map_people_rows,
    map_zafran_rows,
)
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter, WriteReceipt
from clue_api.arv2_wiring import register_arv2_wiring
from clue_api.composition import RESEARCH_PACK_LOADERS
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
from clue_spine import create_brand, create_product, create_project, create_workspace, get_workspace
from clue_storage.artifacts import record_artifact
from clue_storage.fs import FsStorage
from clue_storage.protocol import artifact_key, content_address

#: Where the two answer-key files and the Zafran transcripts live, relative to ``context_root``.
ZAFRAN_DIR = "arv2-one-account-aiark"
PEOPLE_DIR = "arv2-person-depth"

#: The one researched account — the other three were only named by the run.
ZAFRAN_DOMAIN = "zafran.io"

_TRANSCRIPT_MEDIA_TYPE = "text/markdown"
_TRANSCRIPT_SOURCE_KEY = "arv2:answer_key:transcript"
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
_ANSWER_KEY_MARKER = "zafran-2026-09-02"


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

    product_id = await _ensure_spine(conn, manifest)
    await _load_packs(conn)
    accounts, contacts = await _entities(conn, manifest)
    await ensure_project_run(
        conn,
        project_run_id=manifest.project_run_id,
        project_id=manifest.project_id,
        workspace_id=manifest.workspace_id,
        icp_key="answer-key",
        icp_version=1,
        phase=ProjectPhase.DEEP,
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
    await _research_rows(
        conn,
        manifest=manifest,
        product_id=product_id,
        account_id=accounts[ZAFRAN_DOMAIN],
        written=zafran_written,
        committee=committee,
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


async def _ensure_spine(conn: AsyncConnection, manifest: AnswerKeyManifest) -> str:
    """Create workspace → brand → product → project, and return the product id.

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
    return str(product.product_id)


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
    """Create the four accounts (with project membership) and the twelve people under them."""
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
                    "answer_key": _ANSWER_KEY_MARKER,
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


# -- step 9: the terminal research run, job and coverage -----------------------------------------


def _sha256_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def _research_rows(
    conn: AsyncConnection,
    *,
    manifest: AnswerKeyManifest,
    product_id: str,
    account_id: EntityId,
    written: Sequence[tuple[RowDraft, WriteReceipt]],
    committee: Sequence[EntityId],
) -> None:
    """Record the M8D fleet rows that make the account read as researched.

    A terminal run/job/coverage triple is what every downstream reader asks for: the committee read
    resolves its members through the run's coverage row, and the fleet control row is how that run
    is found from the project run at all. They are inserted directly, with ``state='terminal'`` — a
    real run reaches that state by UPDATE, and the immutability triggers guard exactly those
    updates, so replaying a finished run through the drivers is neither possible nor the point.
    """
    research_run_id = uuid.uuid5(ANSWER_KEY_NAMESPACE, "arv2-answer-key:research-run")
    selection_id = uuid.uuid5(ANSWER_KEY_NAMESPACE, "arv2-answer-key:selection")
    job_id = uuid.uuid5(ANSWER_KEY_NAMESPACE, "arv2-answer-key:job:zafran")
    coverage_id = uuid.uuid5(ANSWER_KEY_NAMESPACE, "arv2-answer-key:coverage:zafran")
    scope = {
        "workspace_id": manifest.workspace_id,
        "project_id": manifest.project_id,
        "product_id": product_id,
        "project_run_id": str(manifest.project_run_id),
    }

    lifecycle: dict[str, Any] = {
        "run_id": str(research_run_id),
        "run_kind": "account_research",
        "selection": {
            "selection_id": str(selection_id),
            "subject_type": "account",
            **scope,
            "budget_envelope_ref": _BUDGET_REF,
            "subjects": [{"subject_entity_id": str(account_id)}],
        },
        "origin": _ORIGIN,
    }
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_run
                (research_run_id, run_kind, subject_type, workspace_id, project_id, product_id,
                 project_run_id, selection_id, lifecycle_json, lifecycle_sha256,
                 budget_envelope_ref, budget_cap_cents, concurrency_limit, state, terminal_at)
            VALUES
                (:research_run_id, 'account_research', 'account', :workspace_id, :project_id,
                 :product_id, :project_run_id, :selection_id, CAST(:lifecycle AS jsonb), :sha,
                 :budget_ref, 0, 1, 'terminal', now())
            """
        ),
        {
            "research_run_id": research_run_id,
            **scope,
            "project_run_id": manifest.project_run_id,
            "selection_id": selection_id,
            "lifecycle": json.dumps(lifecycle),
            "sha": _sha256_json(lifecycle),
            "budget_ref": _BUDGET_REF,
        },
    )

    # The fleet control row is how ``latest_account_research_run_id`` finds the run from the
    # project run; without it the committee read never reaches the coverage row below.
    policy = {"origin": _ORIGIN, "supervision": "none"}
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_account_fleet
                (research_run_id, workspace_id, project_id, product_id, project_run_id,
                 canary_job_ids, supervisor_policy_ref, supervisor_policy_json,
                 supervisor_policy_sha256, state, created_by, source_operation_id,
                 source_action_ref, terminal_at)
            VALUES
                (:research_run_id, :workspace_id, :project_id, :product_id, :project_run_id,
                 :canary_job_ids, :policy_ref, CAST(:policy AS jsonb), :policy_sha, 'terminal',
                 :created_by, :operation_id, :action_ref, now())
            """
        ),
        {
            "research_run_id": research_run_id,
            **scope,
            "project_run_id": manifest.project_run_id,
            "canary_job_ids": [job_id],
            "policy_ref": _BUDGET_REF,
            "policy": json.dumps(policy),
            "policy_sha": _sha256_json(policy),
            "created_by": _ORIGIN,
            "operation_id": uuid.uuid5(ANSWER_KEY_NAMESPACE, "arv2-answer-key:operation"),
            "action_ref": f"{_ORIGIN}:zafran",
        },
    )

    thread_id = "answer-key:zafran"
    authorization: dict[str, Any] = {
        "job_id": str(job_id),
        "research_run_id": str(research_run_id),
        "subject_type": "account",
        "subject_entity_id": str(account_id),
        **scope,
        "checkpoint_thread_id": thread_id,
        "selection": dict(scope),
    }
    authorization_sha = _sha256_json(authorization)
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_job
                (job_id, research_run_id, subject_type, subject_entity_id, parent_account_id,
                 workspace_id, project_id, product_id, project_run_id, authorization_json,
                 authorization_sha256, budget_envelope_ref, budget_cap_cents, checkpoint_thread_id,
                 initial_state_sha256, current_state_sha256, state, finalization_outcome,
                 finalization_receipt_ref, terminal_at)
            VALUES
                (:job_id, :research_run_id, 'account', :subject_entity_id, NULL, :workspace_id,
                 :project_id, :product_id, :project_run_id, CAST(:authorization AS jsonb), :sha,
                 :budget_ref, 0, :thread_id, :sha, :sha, 'terminal', 'completed', :receipt_ref,
                 now())
            """
        ),
        {
            "job_id": job_id,
            "research_run_id": research_run_id,
            "subject_entity_id": account_id,
            **scope,
            "project_run_id": manifest.project_run_id,
            "authorization": json.dumps(authorization),
            "sha": authorization_sha,
            "budget_ref": _BUDGET_REF,
            "thread_id": thread_id,
            "receipt_ref": f"{thread_id}:completed",
        },
    )

    account_fields = sorted(
        {draft.field_key for draft, _ in written if draft.entity_type is EntityType.ACCOUNT}
    )
    coverage = {"origin": _ORIGIN, "account_entity_id": str(account_id)}
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_account_coverage
                (coverage_id, research_run_id, job_id, workspace_id, account_entity_id,
                 result_refs, completed_field_keys, unresolved_field_keys, unresolved_reasons,
                 committee_result_refs, committee_member_ids, committee_status, review_flags,
                 claim_refs, evidence_refs, coverage_json, coverage_sha256)
            VALUES
                (:coverage_id, :research_run_id, :job_id, :workspace_id, :account_id,
                 :empty, :completed, :empty, :empty, :empty, :member_ids, 'complete', :empty,
                 :claim_refs, :empty, CAST(:coverage AS jsonb), :sha)
            """
        ),
        {
            "coverage_id": coverage_id,
            "research_run_id": research_run_id,
            "job_id": job_id,
            "workspace_id": manifest.workspace_id,
            "account_id": account_id,
            "empty": [],
            "completed": account_fields,
            "member_ids": list(committee),
            "claim_refs": [f"claim:{receipt.claim_id}" for _, receipt in written],
            "coverage": json.dumps(coverage),
            "sha": _sha256_json(coverage),
        },
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

    Zafran gets the full story — created, researched, committee confirmed. The other three accounts
    were only ever named by the run, so ``created`` is the only honest event for them.
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


__all__ = ["AlreadyLoaded", "LoadReport", "load_answer_key"]
