"""Adapt deterministic provider mappings to the same evidence/assessment write contract.

Mappings are recomputed from the saved original with the existing mapper functions. A caller
cannot turn an arbitrary draft into a provider fact by attaching a plausible JSON path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import (
    JobScope,
    ai_ark_company_claims,
    ai_ark_person_claims,
    ats_posting_claims,
    email_export_claim,
    phone_claim,
)
from clue_api.arv2.ai_ark_client import (
    company_from_record,
    email_export_from_record,
    person_from_record,
    phone_from_record,
)
from clue_api.arv2.ats_client import AtsBoard, AtsKind, BoardPostings, normalise_postings
from clue_api.arv2.claim_writer import (
    ClaimDraft,
    DerivedClaimInput,
    LenientClaimWriter,
    WriteReceipt,
)
from clue_api.arv2.quality_authority import resolve_authority
from clue_api.arv2.quality_claims import ClaimProposal, SemanticAssessment, submit_proposal
from clue_api.arv2.quality_evidence import EvidenceUnavailable, JsonSupport, resolve_source
from clue_api.arv2.structuring_client import FieldCatalog
from clue_core import ClaimId, ExtractionMethod
from clue_research.identity.provider import lock_provider_evidence
from clue_spend.calls import CallCost
from clue_storage import StorageBackend, read_verified_artifact


def _same(a: object, b: object) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _fold(value: str | None) -> str:
    return (
        (value or "")
        .lower()
        .removeprefix("https://")
        .removeprefix("http://")
        .removeprefix("www.")
        .rstrip("/")
    )


class QualityProviderWriter(LenientClaimWriter):
    """Only trusted deterministic acquisitions use this adapter; agent writes use proposals."""

    def __init__(
        self,
        scope: JobScope,
        storage: StorageBackend,
        execution_id: UUID,
        catalog: FieldCatalog,
        *,
        purge: bool,
    ):
        super().__init__(lenient=True, scoped_proposals=True)
        self.scope, self.storage, self.execution_id = scope, storage, execution_id
        self.catalog, self.purge = catalog, purge

    async def write(
        self,
        conn: AsyncConnection,
        draft: ClaimDraft,
        *,
        derivation: DerivedClaimInput | None = None,
        claim_id: ClaimId | None = None,
    ) -> WriteReceipt:
        if claim_id is not None:
            raise ValueError("the provider mapper's claim ids come from its quality proposal")
        if derivation is not None or draft.extraction_method is not ExtractionMethod.API:
            raise ValueError(
                "quality profile requires the typed claim specialist for interpretations"
            )
        if (draft.workspace_id, draft.run_id, draft.entity_id) != (
            self.scope.workspace_id,
            self.scope.run_id,
            self.scope.person_subject_id or self.scope.account_id,
        ):
            raise EvidenceUnavailable("provider mapping belongs to another research subject")
        authority = await resolve_authority(conn, self.scope, self.execution_id)
        subject = draft.markers.get("provider_subject_id")
        if self.scope.person_subject_id:
            if not subject or not draft.artifact_key:
                raise EvidenceUnavailable("person mapping requires a bound provider identity")
            await lock_provider_evidence(
                conn,
                workspace_id=self.scope.workspace_id,
                provider="ai_ark",
                subject_id=str(subject),
                artifact_key=draft.artifact_key,
            )
            bound = (
                await conn.execute(
                    text("""
              SELECT contact_id FROM provider_identity
              WHERE workspace_id=:ws AND provider='ai_ark' AND subject_id=:subject
                AND erased_at IS NULL
            """),
                    {"ws": self.scope.workspace_id, "subject": str(subject)},
                )
            ).scalar_one_or_none()
            if bound != self.scope.person_subject_id:
                raise EvidenceUnavailable("provider identity does not match this person")
        op = draft.markers.get("operation_id")
        ledger = draft.markers.get("quality_ledger_id")
        if not draft.artifact_key and not op and not ledger:
            raise ValueError("provider mapper requires its original operation or ledger identity")
        ids = (
            (
                await conn.execute(
                    text("""
          SELECT source_id FROM arv2_evidence_source
          WHERE workspace_id=:ws AND run_id=:run AND account_id=:account
            AND kind='provider_record'
            AND (CAST(:op AS uuid) IS NULL OR operation_id=CAST(:op AS uuid))
            AND (CAST(:ledger AS uuid) IS NULL OR ledger_id=CAST(:ledger AS uuid))
            AND (CAST(:key AS text) IS NULL OR original_key=CAST(:key AS text))
          ORDER BY revision
        """),
                    {
                        "ws": self.scope.workspace_id,
                        "run": self.scope.run_id,
                        "account": self.scope.account_id,
                        "op": op,
                        "ledger": ledger,
                        "key": draft.artifact_key,
                    },
                )
            )
            .scalars()
            .all()
        )
        matches = []
        for source_id in ids:
            source = await resolve_source(conn, authority.grant, source_id)
            provider = (
                await conn.execute(
                    text("""
              SELECT provider FROM provider_call_ledger WHERE workspace_id=:ws AND ledger_id=:id
            """),
                    {"ws": self.scope.workspace_id, "id": source.ledger_id},
                )
            ).scalar_one_or_none()
            expected_provider = (
                "ai_ark"
                if (draft.source_key or "").startswith("ai_ark:")
                else (draft.source_key or "").removeprefix("ats:")
            )
            if provider != expected_provider:
                continue
            _, raw = await read_verified_artifact(
                conn,
                self.storage,
                workspace_id=self.scope.workspace_id,
                storage_key=source.artifact_key,
            )
            body = json.loads(raw)
            if draft.source_key in {"ai_ark:email_export", "ai_ark:phone"}:
                if not source.original_key:
                    continue
                _, envelope_raw = await read_verified_artifact(
                    conn,
                    self.storage,
                    workspace_id=self.scope.workspace_id,
                    storage_key=source.original_key,
                )
                envelope = json.loads(envelope_raw)
                request = json.loads(
                    envelope.get("record", {}).get("request", {}).get("body_text") or "{}"
                )
                returned = person_from_record(body)
                if returned.ark_id and returned.ark_id != subject:
                    continue
                linked = returned.linkedin_url or body.get("linkedin")
                if (
                    linked
                    and self.scope.person_linkedin_url
                    and _fold(linked) != _fold(self.scope.person_linkedin_url)
                ):
                    continue
                if draft.source_key == "ai_ark:email_export":
                    if request.get("id") != subject:
                        continue
                elif not (
                    (returned.ark_id and returned.ark_id == subject)
                    or (
                        linked
                        and self.scope.person_linkedin_url
                        and _fold(linked) == _fold(self.scope.person_linkedin_url)
                    )
                ):
                    continue
            for pointer, record, candidates in self._candidates(draft, body):
                if any(
                    candidate is not None
                    and candidate.field_key == draft.field_key
                    and _same(candidate.value_json, draft.value_json)
                    for candidate in candidates
                ):
                    matches.append((source, pointer, record))
        if len(matches) != 1:
            raise EvidenceUnavailable(
                "saved provider mapping is missing or ambiguous; inspect the source"
            )
        source, pointer, record = matches[0]
        digest = hashlib.sha256(json.dumps(draft.value_json, sort_keys=True).encode()).hexdigest()[
            :20
        ]
        proposal = ClaimProposal(
            operation_key=f"mapping-v1:{source.source_id}:{draft.field_key}:{digest}",
            field_key=draft.field_key,
            value=draft.value_json,
            support=(
                JsonSupport(source_id=source.source_id, pointer=pointer, expected_value=record),
            ),
            assessment=SemanticAssessment(
                entity="supported",
                field_meaning="supported",
                entailment="supported",
                relationship_direction="not_applicable",
                temporal_scope="supported",
                qualifications=tuple(
                    str(q)
                    for row in draft.value_json
                    if isinstance(row, dict)
                    for q in (
                        cast(list[JsonValue], row["qualifications"])
                        if isinstance(row.get("qualifications"), list)
                        else []
                    )
                )
                if draft.field_key == "account.open_requisitions"
                and isinstance(draft.value_json, list)
                else (),
                explanation="Existing deterministic provider mapper v1, recomputed against saved "
                "original record. Mapping details: "
                + json.dumps(dict(draft.markers), sort_keys=True),
            ),
            identity_binding=draft.identity_binding,
            use_class=draft.use_class,
            outreach_safe=draft.outreach_safe,
        )
        receipt = await submit_proposal(
            conn,
            self.storage,
            self.scope,
            authority.grant,
            proposal,
            context_id=authority.context_id,
            actor_ref="deterministic-provider-mapping:v1",
            purge_unevidenced=self.purge,
        )
        if receipt.claim_id is None:
            raise ValueError(f"provider mapping refused: {receipt.error_code}")
        return WriteReceipt(
            ClaimId(receipt.claim_id),
            draft.field_key,
            {"quality_required": True, "quality_status": receipt.status},
            False,
        )

    def _candidates(
        self, draft: ClaimDraft, body: object
    ) -> Iterator[tuple[str, JsonValue, Sequence[ClaimDraft | None]]]:
        key = draft.source_key or ""
        if key == "ai_ark:company" and isinstance(body, dict):
            for index, record in enumerate(body.get("content", [])):
                if not isinstance(record, dict):
                    continue
                company = company_from_record(record)
                if _fold(company.domain) == _fold(self.scope.account_domain):
                    yield (
                        f"/content/{index}",
                        record,
                        ai_ark_company_claims(company, self.scope, catalog=self.catalog),
                    )
        elif key == "ai_ark:person" and isinstance(body, dict):
            records = (
                list(enumerate(body.get("content", [])))
                if isinstance(body.get("content"), list)
                else [(None, body)]
            )
            for person_index, record in records:
                if not isinstance(record, dict):
                    continue
                person = person_from_record(record)
                subject_id = draft.markers.get("provider_subject_id")
                matched = (subject_id and person.ark_id == subject_id) or (
                    self.scope.person_linkedin_url
                    and _fold(person.linkedin_url) == _fold(self.scope.person_linkedin_url)
                )
                if matched:
                    yield (
                        "" if person_index is None else f"/content/{person_index}",
                        record,
                        ai_ark_person_claims(person, self.scope),
                    )
        elif key in {"ai_ark:email_export", "ai_ark:phone"} and isinstance(body, dict):
            # enrich_channel verifies this operation's bound identity before invoking the mapper.
            if not draft.markers.get("provider_subject_id"):
                return
            mapped = (
                email_export_claim(email_export_from_record(body), self.scope)
                if key.endswith("email_export")
                else phone_claim(phone_from_record(body), self.scope)
            )
            yield "", body, [mapped]
        elif key.startswith("ats:"):
            # The acquisition adapter supplies exact board identity and ledger id from the hop.
            board = draft.markers.get("quality_board")
            if not isinstance(board, dict):
                return
            if (
                board.get("kind") not in ("ashby", "greenhouse", "lever")
                or not isinstance(board.get("slug"), str)
                or not isinstance(board.get("source_url"), str)
            ):
                raise ValueError("invalid source board identity")
            ats = AtsBoard(
                cast(AtsKind, board["kind"]), str(board["slug"]), str(board["source_url"])
            )
            ledger_id = str(draft.markers["quality_ledger_id"])
            postings = BoardPostings(
                board=ats,
                url=str(draft.markers["board_url"]),
                postings=normalise_postings(ats, body, today=self.scope.today),
                raw_ref=None,
                ledger_row_id=ledger_id,
                # Cost is not consumed by the pure mapper. Do not reconstruct or invent a bill.
                cost=CallCost(None, None, None, "unpriced", ledger_id, None, ats.kind, "replay"),
            )
            candidates = ats_posting_claims(postings, self.scope)
            yield "", cast(JsonValue, body), list(candidates)
