"""Workspace-local provider anchors and subject links to multi-person evidence artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityId
from clue_research.identity.entities import get_account, get_contact, insert_contact_entity


class ProviderIdentityConflict(ValueError):
    """A stable source anchor conflicts, is erased, or cannot identify an existing contact."""


def provider_linkedin(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    folded = value.strip().lower().removeprefix("https://").removeprefix("http://")
    return "https://" + folded.removeprefix("www.").rstrip("/")


async def register_provider_subjects(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    provider: str,
    artifact_key: str,
    subjects: Sequence[tuple[str, str | None]],
) -> None:
    any_erased = False
    for subject_id, linkedin in sorted(set(subjects), key=lambda item: (item[0], item[1] or "")):
        await conn.execute(
            text("""
            INSERT INTO
        provider_identity(workspace_id,provider,subject_id,evidence_artifact_key)
            VALUES (:ws,:provider,:subject,:artifact) ON CONFLICT DO NOTHING
        """),
            {
                "ws": workspace_id,
                "provider": provider,
                "subject": subject_id,
                "artifact": artifact_key,
            },
        )
        erased = (
            await conn.execute(
                text("""
            SELECT erased_at IS NOT NULL FROM provider_identity
            WHERE workspace_id=:ws AND provider=:provider AND subject_id=:subject FOR UPDATE
        """),
                {"ws": workspace_id, "provider": provider, "subject": subject_id},
            )
        ).scalar_one()
        any_erased = any_erased or erased
        await conn.execute(
            text("""
            INSERT INTO provider_artifact_subject
              (workspace_id,provider,subject_id,artifact_key,linkedin_url)
            VALUES (:ws,:provider,:subject,:artifact,:linkedin) ON CONFLICT DO NOTHING
        """),
            {
                "ws": workspace_id,
                "provider": provider,
                "subject": subject_id,
                "artifact": artifact_key,
                "linkedin": None if erased else provider_linkedin(linkedin),
            },
        )

    if subjects:
        # All subject locks precede the page lock. A page can contain several people.
        registered = await conn.execute(
            text("""
            UPDATE artifact SET
              expires_at=LEAST(COALESCE(expires_at,now()+interval '30 days'),
                               now()+interval '30 days'),
              privacy_erased=privacy_erased OR :erased,
              erasure_reason=CASE WHEN :erased THEN 'privacy' ELSE erasure_reason END,
              erased_at=CASE WHEN :erased THEN COALESCE(erased_at,now()) ELSE erased_at END,
              source_url=CASE WHEN :erased THEN NULL ELSE source_url END
            WHERE storage_key=:key AND workspace_id=:ws
            """),
            {"key": artifact_key, "ws": workspace_id, "erased": any_erased},
        )
        if registered.rowcount != 1:
            raise ProviderIdentityConflict("provider_artifact_scope_invalid")


async def resolve_provider_contact(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: EntityId,
    provider: str,
    subject_id: str,
    name: str,
    linkedin_url: str | None,
    artifact_key: str,
    require_account_match: bool = True,
) -> tuple[EntityId, bool]:
    """Resolve anchors consistently; never move employment or merge two people by name alone."""
    account = await get_account(conn, account_id)
    if account is None or account.workspace_id != workspace_id or not subject_id or not name:
        raise ProviderIdentityConflict("provider_subject_scope_invalid")
    linkedin = provider_linkedin(linkedin_url)
    keys = {f"provider:{workspace_id}:{provider}:{subject_id}"}
    if linkedin:
        keys.add(f"linkedin:{workspace_id}:{linkedin}")
    for key in sorted(keys):
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key}
        )
    await register_provider_subjects(
        conn,
        workspace_id=workspace_id,
        provider=provider,
        artifact_key=artifact_key,
        subjects=[(subject_id, linkedin)],
    )
    binding = (
        (
            await conn.execute(
                text("""
        SELECT contact_id,erased_at FROM provider_identity
        WHERE workspace_id=:ws AND provider=:provider AND subject_id=:subject FOR UPDATE
    """),
                {"ws": workspace_id, "provider": provider, "subject": subject_id},
            )
        )
        .mappings()
        .one()
    )
    if binding["erased_at"]:
        raise ProviderIdentityConflict("provider_identity_erased")
    url_id = None
    if linkedin:
        url_id = (
            await conn.execute(
                text("""
            SELECT id FROM contact_entity WHERE workspace_id=:ws
              AND regexp_replace(lower(rtrim(linkedin_url,'/')), '^https?://(www[.])?', '')
                  =regexp_replace(:url, '^https?://', '')
        """),
                {"ws": workspace_id, "url": linkedin},
            )
        ).scalar_one_or_none()
    bound = binding["contact_id"]
    if bound and url_id and bound != url_id:
        raise ProviderIdentityConflict("provider_linkedin_conflict")
    contact_id = bound or url_id
    if contact_id:
        held = await get_contact(conn, EntityId(contact_id))
        if (
            held is None
            or held.workspace_id != workspace_id
            or (require_account_match and str(held.account_entity_id) != str(account_id))
        ):
            raise ProviderIdentityConflict("employment_conflict")
        if held.merged_into is not None:
            raise ProviderIdentityConflict("merged_identity_requires_resolution")
        if linkedin and held.linkedin_url and provider_linkedin(held.linkedin_url) != linkedin:
            raise ProviderIdentityConflict("provider_linkedin_conflict")
        other_binding = (
            await conn.execute(
                text("""
            SELECT EXISTS(SELECT 1 FROM provider_identity WHERE workspace_id=:ws
              AND provider=:provider AND contact_id=:contact AND subject_id<>:subject)
        """),
                {
                    "ws": workspace_id,
                    "provider": provider,
                    "contact": contact_id,
                    "subject": subject_id,
                },
            )
        ).scalar_one()
        if other_binding:
            raise ProviderIdentityConflict("distinct_provider_identity")
        created = False
    else:
        # Exact names alone cannot prove a provider record is the existing same-name colleague.
        exists = (
            await conn.execute(
                text("""
            SELECT EXISTS(SELECT 1 FROM contact_entity c WHERE workspace_id=:ws
              AND account_entity_id=:account AND lower(full_name)=lower(:name)
              AND NOT EXISTS (SELECT 1 FROM provider_identity p WHERE p.workspace_id=:ws
                AND p.provider=:provider AND p.contact_id=c.id))
        """),
                {"ws": workspace_id, "account": account_id, "name": name, "provider": provider},
            )
        ).scalar_one()
        if exists:
            raise ProviderIdentityConflict("ambiguous_name")
        contact_id = await insert_contact_entity(
            conn, account_entity_id=account_id, full_name=name, linkedin_url=linkedin
        )
        created = True
    await conn.execute(
        text("""
        UPDATE provider_identity SET contact_id=:contact,evidence_artifact_key=:artifact
        WHERE workspace_id=:ws AND provider=:provider AND subject_id=:subject
    """),
        {
            "contact": contact_id,
            "artifact": artifact_key,
            "ws": workspace_id,
            "provider": provider,
            "subject": subject_id,
        },
    )
    return EntityId(contact_id), created


async def provider_selection_ids(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    contact_id: EntityId,
) -> list[UUID]:
    return list(
        (
            await conn.execute(
                text("""
        SELECT DISTINCT s.claim_id FROM provider_selection_claim s
        JOIN provider_identity p USING(workspace_id,provider,subject_id)
        WHERE s.workspace_id=:ws AND (p.contact_id=:contact OR EXISTS (
          SELECT 1 FROM provider_artifact_subject a JOIN contact_entity c
            ON replace(replace(lower(rtrim(c.linkedin_url,'/')),
               '://www.', '://'),'http://','https://')=a.linkedin_url
             AND c.workspace_id=a.workspace_id
          WHERE a.workspace_id=s.workspace_id AND a.provider=s.provider
            AND a.subject_id=s.subject_id AND c.id=:contact))
    """),
                {"ws": workspace_id, "contact": contact_id},
            )
        )
        .scalars()
        .all()
    )


async def erase_provider_evidence(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    contact_id: EntityId,
) -> list[str]:
    """Invalidate entire shared pages; other subjects retain facts with unavailable evidence."""
    subjects = (
        await conn.execute(
            text("""
        SELECT DISTINCT p.provider,p.subject_id FROM provider_identity p
        LEFT JOIN provider_artifact_subject a USING(workspace_id,provider,subject_id)
        LEFT JOIN contact_entity c ON c.workspace_id=a.workspace_id
          AND replace(replace(lower(rtrim(c.linkedin_url,'/')),
            '://www.','://'),'http://','https://')=a.linkedin_url
        WHERE p.workspace_id=:ws AND (p.contact_id=:contact OR c.id=:contact)
    """),
            {"ws": workspace_id, "contact": contact_id},
        )
    ).all()
    keys: list[str] = []
    for provider, subject_id in sorted(subjects):
        params = {"ws": workspace_id, "provider": provider, "subject": subject_id}
        await conn.execute(
            text("""
            UPDATE provider_identity SET erased_at=COALESCE(erased_at,now())
            WHERE workspace_id=:ws AND provider=:provider AND subject_id=:subject
        """),
            params,
        )
    for provider, subject_id in sorted(subjects):
        params = {"ws": workspace_id, "provider": provider, "subject": subject_id}
        keys.extend(
            (
                await conn.execute(
                    text("""
            UPDATE artifact SET
        privacy_erased=true,erasure_reason='privacy',erased_at=now(),source_url=NULL
            WHERE workspace_id=:ws AND storage_key IN (
              SELECT artifact_key FROM provider_artifact_subject
              WHERE workspace_id=:ws AND provider=:provider AND subject_id=:subject)
            RETURNING storage_key
        """),
                    params,
                )
            )
            .scalars()
            .all()
        )
        await conn.execute(
            text("""
            UPDATE provider_artifact_subject SET linkedin_url=NULL
            WHERE workspace_id=:ws AND provider=:provider AND subject_id=:subject
        """),
            params,
        )
    return sorted(set(keys))


async def lock_provider_evidence(
    conn: AsyncConnection, *, workspace_id: str, provider: str, subject_id: str, artifact_key: str
) -> None:
    """Share the erasure lock order so cached drafts cannot outlive subject erasure."""
    erased = (
        await conn.execute(
            text("""
        SELECT erased_at IS NOT NULL FROM provider_identity
        WHERE workspace_id=:ws AND provider=:provider AND subject_id=:subject FOR UPDATE
    """),
            {"ws": workspace_id, "provider": provider, "subject": subject_id},
        )
    ).scalar_one_or_none()
    if erased is None or erased:
        raise ProviderIdentityConflict("provider_identity_unavailable")
    live = (
        await conn.execute(
            text("""
        SELECT erased_at IS NULL AND (expires_at IS NULL OR expires_at>now()) FROM artifact
        WHERE workspace_id=:ws AND storage_key=:key FOR UPDATE
    """),
            {"ws": workspace_id, "key": artifact_key},
        )
    ).scalar_one_or_none()
    if not live:
        raise ProviderIdentityConflict("provider_evidence_unavailable")


async def link_selection_claim(
    conn: AsyncConnection, *, workspace_id: str, contact_id: EntityId, claim_id: UUID
) -> None:
    """Tie account-side assessment copies to the resolved contact, including web-only members."""
    await conn.execute(
        text("""
        INSERT INTO provider_identity(workspace_id,provider,subject_id,contact_id)
        VALUES (:ws,'arv2-contact',:subject,:contact) ON CONFLICT DO NOTHING
    """),
        {"ws": workspace_id, "subject": str(contact_id), "contact": contact_id},
    )
    await conn.execute(
        text("""
        INSERT INTO provider_selection_claim(workspace_id,provider,subject_id,claim_id)
        VALUES (:ws,'arv2-contact',:subject,:claim) ON CONFLICT DO NOTHING
    """),
        {"ws": workspace_id, "subject": str(contact_id), "claim": claim_id},
    )
