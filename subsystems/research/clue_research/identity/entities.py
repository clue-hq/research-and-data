"""The canonical entity store — the ``entity_id`` seam (M2.1).

This is the thin read/write API over ``account_entity`` / ``contact_entity`` that the *entire*
subsystem keys on (conventions §2: everything keys on a resolved ``entity_id``, never a free-text
name). Resolution logic (M2.2 fuzzy matching, M2.3 merge decisioning) is built *on top of* this
store; everything else (claim store, discovery, profiling, scoring, handoff) consumes ids from here
and never re-implements entity persistence. Swapping the persistence engine stays behind this API —
nothing downstream queries the tables directly.

What lives here (M2.1):

* **writes** — :func:`insert_account_entity`, :func:`insert_contact_entity` (normalizing strong
  keys + building the normalized match-key index), :func:`update_account` (the canonicalization
  write M2.2/M2.3 drive), :func:`enrich_account` (its conservative, gap-filling half — what a *new
  sighting* of an account that already exists may change), :func:`set_status`, :func:`mark_merged`.
* **reads** — :func:`get_account`, :func:`get_contact`, :func:`get_entity`, and
  :func:`resolve_alias` (exact strong-key / normalized-alias lookup — *fuzzy is M2.2*).
* **merge-chain** — :func:`surviving_id` follows a ``merged_into`` chain to the live survivor in one
  call and **errors on a cycle** (never infinite-loops), per the §M2.1 acceptance criteria.

Normal forms come from :mod:`clue_research.identity.normalize` (the one folding path, shared with
M2.2). ``aliases`` is stored as the *normalized match index* — the set of name-keys an exact lookup
can hit — so ``resolve_alias`` is an indexed equality check, not a scan. Persistence follows the
claim store's seam style: callers pass an :class:`~sqlalchemy.ext.asyncio.AsyncConnection`; no
business SQL lives in ``db/``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import ARRAY, String, Text, bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountEntity,
    AccountStatus,
    ContactEntity,
    EntityId,
    EntityType,
    decode_jsonb,
    serialize_value_json,
)
from clue_research.identity.normalize import (
    canonical_registry_id,
    name_key,
    normalize_name,
    registrable_domain,
)
from clue_research.membership import repoint_project_accounts

# A safety cap on the merged_into walk, independent of the cycle guard — a defensive bound so a
# pathologically long (but acyclic) chain can never hang a read either.
_MAX_MERGE_HOPS = 64


class MergeCycleError(ValueError):
    """Raised when a ``merged_into`` chain forms a cycle (detected, never infinite-looped)."""


class UnknownEntityTypeError(ValueError):
    """Raised when an ``entity_type`` has no entity table (only account/contact exist)."""


class CrossWorkspaceMergeError(ValueError):
    """Merge loser and survivor live in different workspaces — forbidden (accounts are
    workspace-local; founder ruling 2026-07-22). The composite merge FK backstops this."""


def _table(entity_type: EntityType) -> str:
    if entity_type is EntityType.ACCOUNT:
        return "account_entity"
    if entity_type is EntityType.CONTACT:
        return "contact_entity"
    raise UnknownEntityTypeError(f"no entity table for entity_type {entity_type!r}")


def _match_keys(canonical_name: str, aliases: Sequence[str]) -> list[str]:
    """The normalized match index stored in ``aliases``: every name-key an exact lookup can hit.

    Includes both the suffix-stripped key (``name_key``) and the plain normalized form of the
    canonical name and each supplied alias, de-duplicated, empties dropped. So ``resolve_alias``
    can match ``"Acme Inc"`` against a stored ``"Acme"`` (and vice-versa) by equality alone.
    """
    keys: set[str] = set()
    for raw in (canonical_name, *aliases):
        for folded in (normalize_name(raw), name_key(raw)):
            if folded:
                keys.add(folded)
    return sorted(keys)


def _registry_map(registry_ids: Mapping[str, str] | None) -> dict[str, str]:
    """Canonicalize a registry map to ``{NAMESPACE_UPPER: compact_value}`` (dropping empties)."""
    out: dict[str, str] = {}
    for ns, value in (registry_ids or {}).items():
        norm_ns, norm_value = canonical_registry_id(ns, value)
        if norm_value:
            out[norm_ns] = norm_value
    return out


def _normalize_strong_text(value: str | None) -> str | None:
    """Lower-case + trim a strong-key string column (linkedin_url / verified_email); ``None`` stays
    ``None``. A trailing slash on a profile URL is dropped so it folds with the un-slashed form."""
    if value is None:
        return None
    folded = value.strip().rstrip("/").lower()
    return folded or None


_ACCOUNT_COLUMNS = (
    "id, canonical_name, primary_domain, aliases, hq_geo, registry_ids, status, merged_into, "
    "canonical_version, workspace_id"
)
_CONTACT_COLUMNS = (
    "id, account_entity_id, full_name, linkedin_url, verified_email, aliases, geo, "
    "jurisdiction, status, merged_into, canonical_version, workspace_id"
)


def _row_to_account(row: Mapping[str, object]) -> AccountEntity:
    # Column names match AccountEntity field names exactly; pydantic coerces list→tuple, validates
    # the uuid/enum fields, and re-runs the model invariants (defense in depth on read).
    return AccountEntity.model_validate(
        {
            **row,
            "hq_geo": decode_jsonb(row["hq_geo"]),
            "registry_ids": decode_jsonb(row["registry_ids"]) or {},
        }
    )


def _row_to_contact(row: Mapping[str, object]) -> ContactEntity:
    return ContactEntity.model_validate({**row, "geo": decode_jsonb(row["geo"])})


# --- writes -----------------------------------------------------------------
_INSERT_ACCOUNT = text(
    """
    INSERT INTO account_entity (canonical_name, primary_domain, aliases, hq_geo, registry_ids,
                                status, workspace_id, owner_user_id, created_by_user_id)
    VALUES (:canonical_name, :primary_domain, :aliases, CAST(:hq_geo AS jsonb),
            CAST(:registry_ids AS jsonb), CAST(:status AS entity_status), :workspace_id,
            :owner_user_id, :created_by_user_id)
    RETURNING id
    """
).bindparams(bindparam("aliases", type_=ARRAY(String())))


async def insert_account_entity(
    conn: AsyncConnection,
    *,
    canonical_name: str,
    primary_domain: str | None = None,
    aliases: Sequence[str] = (),
    hq_geo: Mapping[str, object] | None = None,
    registry_ids: Mapping[str, str] | None = None,
    status: AccountStatus = AccountStatus.CANDIDATE,
    workspace_id: str,
    owner_user_id: str | None = None,
    created_by_user_id: str | None = None,
) -> EntityId:
    """Insert a canonical account entity, normalizing its strong keys + match index; return its id.

    ``created_by_user_id`` is the human whose action made the account exist (the requester of a
    discovery run, the actor of a manual create); ``owner_user_id`` is who owns it on the accounts
    table. Founder ruling 2026-09-11: **the creator is the owner by default** — callers pass the
    same id for both until an ownership mechanism exists. Both stay ``None`` for machine-made rows
    with no human behind them (fixtures, loaders).

    ``primary_domain`` is folded to its registrable form; ``registry_ids`` keys/values are
    canonicalized; ``aliases`` is stored as the normalized match index (see :func:`_match_keys`).
    Strong-key collisions raise (the partial-unique constraints) — that is the deterministic dedup
    guard, surfaced to the caller (M2.3 turns it into a merge). Strong-key uniqueness is
    *workspace-scoped* (accounts are workspace-local; founder ruling 2026-07-22): the same
    domain/registry id under two workspaces coexists.

    ``workspace_id`` is **required** (accounts are workspace-local — [B3×research] Task 3): every
    creation chain threads the caller's workspace, and the row's composite workspace anchor backs
    the contact→account and merge fences. Migration ``82a80fb80c9e`` makes the column ``NOT NULL``.
    """
    result = await conn.execute(
        _INSERT_ACCOUNT,
        {
            "canonical_name": canonical_name,
            "primary_domain": registrable_domain(primary_domain) if primary_domain else None,
            "aliases": _match_keys(canonical_name, aliases),
            "hq_geo": serialize_value_json(dict(hq_geo)) if hq_geo is not None else None,
            "registry_ids": serialize_value_json(_registry_map(registry_ids)),
            "status": status.value,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            "created_by_user_id": created_by_user_id,
        },
    )
    return EntityId(result.scalar_one())


# The contact's workspace is stamped from its parent account *inside* the INSERT (a subquery), so a
# contact can never disagree with its account's workspace — the composite FK
# (account_entity_id, workspace_id) → account_entity (id, workspace_id) would reject a mismatch, and
# stamping it atomically removes the window where it could be wrong.
_INSERT_CONTACT = text(
    """
    INSERT INTO contact_entity (account_entity_id, full_name, linkedin_url, verified_email,
                                aliases, geo, jurisdiction, status, workspace_id)
    VALUES (:account_entity_id, :full_name, :linkedin_url, :verified_email, :aliases,
            CAST(:geo AS jsonb), :jurisdiction, CAST(:status AS entity_status),
            (SELECT workspace_id FROM account_entity WHERE id = :account_entity_id))
    RETURNING id
    """
).bindparams(bindparam("aliases", type_=ARRAY(String())))


async def insert_contact_entity(
    conn: AsyncConnection,
    *,
    account_entity_id: EntityId,
    full_name: str | None = None,
    linkedin_url: str | None = None,
    verified_email: str | None = None,
    aliases: Sequence[str] = (),
    geo: Mapping[str, object] | None = None,
    jurisdiction: str | None = None,
    status: AccountStatus = AccountStatus.CANDIDATE,
) -> EntityId:
    """Insert a contact under an account (the FK is required — contacts resolve under accounts).

    ``linkedin_url`` / ``verified_email`` are folded (lower-cased, trailing slash dropped); the
    match index is built from ``full_name`` + ``aliases``. A duplicate strong key raises.
    """
    result = await conn.execute(
        _INSERT_CONTACT,
        {
            "account_entity_id": account_entity_id,
            "full_name": full_name,
            "linkedin_url": _normalize_strong_text(linkedin_url),
            "verified_email": _normalize_strong_text(verified_email),
            "aliases": _match_keys(full_name or "", aliases),
            "geo": serialize_value_json(dict(geo)) if geo is not None else None,
            "jurisdiction": jurisdiction,
            "status": status.value,
        },
    )
    return EntityId(result.scalar_one())


async def promote_contact_verified_email(
    conn: AsyncConnection,
    *,
    contact_entity_id: EntityId,
    verified_email: str,
) -> None:
    """Apply an already-governed email promotion to one canonical contact.

    This is deliberately a narrow identity mutation, not a validator. C5 must first prove its
    observed claim, strong independent validation, exact operation, and use decision. The entity
    layer only enforces canonical ownership, no conflicting strong key, and idempotent replay.
    """

    normalized = _normalize_strong_text(verified_email)
    if normalized is None:
        raise ValueError("verified email promotion requires a non-empty email")
    row = (
        await conn.execute(
            text("SELECT verified_email, merged_into FROM contact_entity WHERE id=:id FOR UPDATE"),
            {"id": contact_entity_id},
        )
    ).one_or_none()
    if row is None or row.merged_into is not None:
        raise ValueError("verified email promotion requires a canonical contact")
    if row.verified_email is not None and row.verified_email != normalized:
        raise ValueError("contact already has a different verified email")
    owner = (
        await conn.execute(
            text("SELECT id FROM contact_entity WHERE verified_email=:email AND id<>:id LIMIT 1"),
            {"email": normalized, "id": contact_entity_id},
        )
    ).scalar_one_or_none()
    if owner is not None:
        raise ValueError("verified email belongs to another contact")
    if row.verified_email == normalized:
        return
    await conn.execute(
        text(
            "UPDATE contact_entity SET verified_email=:email, "
            "canonical_version=canonical_version+1, "
            "updated_at=now() WHERE id=:id"
        ),
        {"email": normalized, "id": contact_entity_id},
    )


async def update_account(
    conn: AsyncConnection,
    entity_id: EntityId,
    *,
    canonical_name: str | None = None,
    primary_domain: str | None = None,
    add_aliases: Sequence[str] = (),
    add_registry_ids: Mapping[str, str] | None = None,
    hq_geo: Mapping[str, object] | None = None,
) -> None:
    """The canonicalization write (M2.2 chooses, M2.3 applies): union new aliases / registry ids and
    optionally set a better canonical_name / primary_domain / hq_geo on the *survivor*.

    Aliases are unioned into the normalized match index; registry ids are canonicalized and merged
    (the survivor's existing values win on key collision — its already-resolved id is
    authoritative). ``updated_at`` is bumped. Entity rows are mutable (unlike append-only claims);
    this is the sanctioned mutation path.

    Every column this writes participates in the ``account_entity_bump_canonical_version`` trigger,
    so ``canonical_version`` advances **iff** one of them actually changes — a call whose values are
    already stored touches only ``updated_at`` and leaves the durable revision alone. Callers that
    care about not bumping (:func:`enrich_account`) therefore only have to avoid passing a no-op
    ``add_aliases`` (the array is rewritten set-wise, and set order is not stable).
    """
    sets = ["updated_at = now()"]
    params: dict[str, object] = {"id": entity_id}
    needs_array = False
    if canonical_name is not None:
        sets.append("canonical_name = :canonical_name")
        params["canonical_name"] = canonical_name
    if primary_domain is not None:
        sets.append("primary_domain = :primary_domain")
        params["primary_domain"] = registrable_domain(primary_domain)
    if hq_geo is not None:
        sets.append("hq_geo = CAST(:hq_geo AS jsonb)")
        params["hq_geo"] = serialize_value_json(dict(hq_geo))
    new_keys = _match_keys("", add_aliases) if add_aliases else []
    if new_keys:
        # Append only the keys not already present (array union, de-duplicated).
        sets.append("aliases = ARRAY(SELECT DISTINCT unnest(aliases || :new_keys))")
        params["new_keys"] = new_keys
        needs_array = True
    reg = _registry_map(add_registry_ids)
    if reg:
        # Incoming keys fill only gaps: existing registry_ids (right) wins on collision (|| order).
        sets.append("registry_ids = CAST(:add_registry AS jsonb) || registry_ids")
        params["add_registry"] = serialize_value_json(reg)
    stmt = text(f"UPDATE account_entity SET {', '.join(sets)} WHERE id = :id")
    if needs_array:
        # text[] || text[] requires matching element types (varchar[] would not match the column).
        stmt = stmt.bindparams(bindparam("new_keys", type_=ARRAY(Text())))
    await conn.execute(stmt, params)


async def _strong_key_is_free(
    conn: AsyncConnection, sql: str, params: Mapping[str, object]
) -> bool:
    """Is a workspace-scoped strong key unheld by any *other* account? (the pre-check that lets an
    enrichment skip a fill instead of raising into its caller's transaction)."""
    return (await conn.execute(text(sql), dict(params))).first() is None


_DOMAIN_HELD = (
    "SELECT 1 FROM account_entity "
    "WHERE workspace_id = :ws AND primary_domain = :domain AND id <> :id LIMIT 1"
)
_REGISTRY_HELD = (
    "SELECT 1 FROM account_entity "
    "WHERE workspace_id = :ws AND registry_ids->>:ns = :value AND id <> :id LIMIT 1"
)


async def enrich_account(
    conn: AsyncConnection,
    entity_id: EntityId,
    *,
    workspace_id: str,
    primary_domain: str | None = None,
    add_aliases: Sequence[str] = (),
    add_registry_ids: Mapping[str, str] | None = None,
    hq_geo: Mapping[str, object] | None = None,
) -> bool:
    """Fold a *new sighting's* identifiers into an account that already exists (FI-2 §8.2-H2).

    The conservative half of :func:`update_account`: an observation that resolves onto an existing
    account is evidence about that account, so its aliases and registry ids are absorbed and its
    ``primary_domain`` / ``hq_geo`` fill a **gap** — but nothing the survivor already asserts is
    overwritten, and ``canonical_name`` is never touched (renaming an account on a sighting is a
    canonicalization decision, and canonicalization only happens on a confirmed merge).

    Precisely: ``aliases`` ∪ new keys; ``registry_ids`` ∪ new namespaces (**survivor wins** on a
    namespace it already holds); ``primary_domain`` / ``hq_geo`` set only when the survivor's is
    ``NULL``. A strong key another account of this workspace already holds is **skipped**, not
    written — the sighting is enriching, not re-keying, and a unique-index violation must never
    abort the caller's ingest. The write runs in a ``SAVEPOINT`` so the race the pre-check cannot
    close (a concurrent writer taking the key in between) degrades to the same skip.

    Returns whether anything was written. Nothing to add → **no UPDATE at all**, so a repeated
    sighting leaves ``canonical_version`` (C7 view identity) exactly where it was.
    """
    survivor = await get_account(conn, entity_id)
    if survivor is None or survivor.merged_into is not None:
        return False  # a merged loser is a redirect; enrich its survivor, not it
    if survivor.workspace_id != workspace_id:
        # Unreachable through resolution (every candidate query is workspace-scoped), so reaching
        # it means a caller crossed tenancy by hand — refuse loudly rather than write.
        raise CrossWorkspaceMergeError(
            f"cannot enrich account {entity_id} of workspace {survivor.workspace_id!r} "
            f"from an observation resolved in {workspace_id!r}"
        )

    aliases = tuple(alias for alias in add_aliases if alias and alias.strip())
    # The stored column is the normalized match index, so "new" is measured in keys, not strings.
    # Passing aliases that fold to keys already present would rewrite the array set-wise (order is
    # not stable) and bump canonical_version for no identity change.
    if not set(_match_keys("", aliases)) - set(survivor.aliases):
        aliases = ()

    registry: dict[str, str] = {}
    for namespace, value in _registry_map(add_registry_ids).items():
        if namespace in survivor.registry_ids:
            continue  # survivor wins: its already-resolved id is authoritative
        if await _strong_key_is_free(
            conn,
            _REGISTRY_HELD,
            {"ws": workspace_id, "ns": namespace, "value": value, "id": entity_id},
        ):
            registry[namespace] = value

    domain: str | None = None
    if survivor.primary_domain is None and primary_domain:
        folded = registrable_domain(primary_domain)
        if folded and await _strong_key_is_free(
            conn, _DOMAIN_HELD, {"ws": workspace_id, "domain": folded, "id": entity_id}
        ):
            domain = folded

    geo = dict(hq_geo) if hq_geo is not None and survivor.hq_geo is None else None

    if not (aliases or registry or domain or geo):
        return False
    try:
        async with conn.begin_nested():
            await update_account(
                conn,
                entity_id,
                primary_domain=domain,
                add_aliases=aliases,
                add_registry_ids=registry,
                hq_geo=geo,
            )
    except IntegrityError:
        # A concurrent writer took a strong key between the pre-check and this write. The savepoint
        # is rolled back; retry with only the fields no unique index guards — which drops *every*
        # strong key this call would have added, not just the contested one (the loser is at most
        # one round of enrichment; the next sighting re-attempts from scratch).
        if not (aliases or geo):
            return False
        async with conn.begin_nested():
            await update_account(conn, entity_id, add_aliases=aliases, hq_geo=geo)
    return True


async def set_status(
    conn: AsyncConnection, entity_type: EntityType, entity_id: EntityId, status: AccountStatus
) -> None:
    """Advance an entity's lifecycle status (candidate → active → merged). Merging uses
    :func:`mark_merged` (which sets ``merged_into`` atomically with the status)."""
    table = _table(entity_type)
    await conn.execute(
        text(
            f"UPDATE {table} SET status = CAST(:status AS entity_status), updated_at = now() "
            "WHERE id = :id"
        ),
        {"status": status.value, "id": entity_id},
    )


async def mark_merged(
    conn: AsyncConnection, entity_type: EntityType, loser_id: EntityId, survivor_id: EntityId
) -> None:
    """Point ``loser`` at ``survivor``: set ``status='merged'`` and ``merged_into`` in one UPDATE
    (the ``merged ⟺ merged_into`` CHECK is satisfied atomically). Idempotent on the pair.

    Refuses a cross-workspace pair (accounts are workspace-local; founder ruling 2026-07-22) with a
    clear :class:`CrossWorkspaceMergeError` *before* the composite merge FK would fire.

    For an account, the loser's FI-2 ``project_account`` memberships re-point to the survivor in
    this same transaction (spec §2), so membership is never orphaned on a merged-away account and
    no caller has to remember the second step."""
    if loser_id == survivor_id:
        raise MergeCycleError("an entity cannot be merged into itself")
    table = _table(entity_type)
    scopes = {
        row["id"]: row["workspace_id"]
        for row in (
            await conn.execute(
                text(f"SELECT id, workspace_id FROM {table} WHERE id IN (:a, :b)"),
                {"a": loser_id, "b": survivor_id},
            )
        )
        .mappings()
        .all()
    }
    if scopes.get(loser_id) != scopes.get(survivor_id):
        raise CrossWorkspaceMergeError(
            f"cannot merge across workspaces: "
            f"{scopes.get(loser_id)!r} -> {scopes.get(survivor_id)!r}"
        )
    await conn.execute(
        text(
            f"UPDATE {table} SET status = 'merged', merged_into = :survivor, updated_at = now() "
            "WHERE id = :loser"
        ),
        {"survivor": survivor_id, "loser": loser_id},
    )
    # The survivor's canonical membership changed even when none of its visible scalar columns
    # did. Bump its durable revision explicitly so C7 view/snapshot identity changes as well.
    await conn.execute(
        text(
            f"UPDATE {table} SET canonical_version = canonical_version + 1, updated_at = now() "
            "WHERE id = :survivor"
        ),
        {"survivor": survivor_id},
    )
    # FI-2 §2: project membership follows the survivor. Accounts only — a contact has no
    # ``project_account`` row. ``workspace_id`` is the pair's (already agreed) workspace; it is
    # None only when neither row exists, in which case the UPDATEs above were no-ops too.
    workspace_id = scopes.get(loser_id)
    if entity_type is EntityType.ACCOUNT and workspace_id is not None:
        await repoint_project_accounts(
            conn, workspace_id=workspace_id, loser_id=loser_id, survivor_id=survivor_id
        )


# --- reads ------------------------------------------------------------------
async def get_account(conn: AsyncConnection, entity_id: EntityId) -> AccountEntity | None:
    """Return the full typed :class:`AccountEntity`, or ``None``. A merged entity surfaces its
    ``merged_into`` pointer (the read does not silently follow it — use :func:`surviving_id`)."""
    row = (
        (
            await conn.execute(
                text(f"SELECT {_ACCOUNT_COLUMNS} FROM account_entity WHERE id = :id"),
                {"id": entity_id},
            )
        )
        .mappings()
        .first()
    )
    return _row_to_account(dict(row)) if row is not None else None


async def get_contact(conn: AsyncConnection, entity_id: EntityId) -> ContactEntity | None:
    """Return the full typed :class:`ContactEntity`, or ``None`` (merged surfaces its pointer)."""
    row = (
        (
            await conn.execute(
                text(f"SELECT {_CONTACT_COLUMNS} FROM contact_entity WHERE id = :id"),
                {"id": entity_id},
            )
        )
        .mappings()
        .first()
    )
    return _row_to_contact(dict(row)) if row is not None else None


async def get_accounts(
    conn: AsyncConnection, entity_ids: Sequence[EntityId]
) -> dict[EntityId, AccountEntity]:
    """Batch-load canonical account rows by exact id."""
    if not entity_ids:
        return {}
    stmt = text(
        f"SELECT {_ACCOUNT_COLUMNS} FROM account_entity WHERE id IN :ids ORDER BY id"
    ).bindparams(bindparam("ids", expanding=True))
    rows = (await conn.execute(stmt, {"ids": list(entity_ids)})).mappings().all()
    return {account.id: account for account in (_row_to_account(dict(row)) for row in rows)}


async def get_contacts(
    conn: AsyncConnection, entity_ids: Sequence[EntityId]
) -> dict[EntityId, ContactEntity]:
    """Batch-load canonical contact rows by exact id."""
    if not entity_ids:
        return {}
    stmt = text(
        f"SELECT {_CONTACT_COLUMNS} FROM contact_entity WHERE id IN :ids ORDER BY id"
    ).bindparams(bindparam("ids", expanding=True))
    rows = (await conn.execute(stmt, {"ids": list(entity_ids)})).mappings().all()
    return {contact.id: contact for contact in (_row_to_contact(dict(row)) for row in rows)}


async def canonical_member_ids(
    conn: AsyncConnection,
    survivor_id: EntityId,
    entity_type: EntityType,
    *,
    workspace_id: str,
) -> tuple[EntityId, ...]:
    """Return the exact identity rows whose merge chain terminates at ``survivor_id``.

    Immutable claims remain keyed to their origin row after an identity merge. C7 uses this
    bounded, workspace-scoped membership set to retain those claims without rewriting history.
    """
    table = _table(entity_type)
    rows = (
        await conn.execute(
            text(
                f"""
                WITH RECURSIVE members(id, depth) AS (
                    SELECT id, 0
                    FROM {table}
                    WHERE id = :survivor_id
                      AND workspace_id = :workspace_id
                    UNION ALL
                    SELECT candidate.id, members.depth + 1
                    FROM {table} candidate
                    JOIN members ON candidate.merged_into = members.id
                    WHERE candidate.workspace_id = :workspace_id
                      AND members.depth < :max_hops
                )
                SELECT DISTINCT id
                FROM members
                ORDER BY id
                """
            ),
            {
                "survivor_id": survivor_id,
                "workspace_id": workspace_id,
                "max_hops": _MAX_MERGE_HOPS,
            },
        )
    ).scalars()
    return tuple(EntityId(value) for value in rows)


async def surviving_ids(
    conn: AsyncConnection,
    entity_ids: Sequence[EntityId],
    entity_type: EntityType,
    *,
    workspace_id: str,
) -> dict[EntityId, EntityId]:
    """Resolve several merge chains in one bounded recursive query."""

    ids = tuple(dict.fromkeys(entity_ids))
    if not ids:
        return {}
    table = _table(entity_type)
    stmt = text(
        f"""
        WITH RECURSIVE paths(origin_id, current_id, merged_into, depth) AS (
            SELECT id, id, merged_into, 0
            FROM {table}
            WHERE id IN :entity_ids AND workspace_id = :workspace_id
            UNION ALL
            SELECT paths.origin_id, next.id, next.merged_into, paths.depth + 1
            FROM paths
            JOIN {table} next ON next.id = paths.merged_into
            WHERE paths.merged_into IS NOT NULL
              AND next.workspace_id = :workspace_id
              AND paths.depth < :max_hops
        )
        SELECT DISTINCT ON (origin_id) origin_id, current_id
        FROM paths
        ORDER BY origin_id, depth DESC
        """
    ).bindparams(bindparam("entity_ids", expanding=True))
    rows = (
        await conn.execute(
            stmt,
            {
                "entity_ids": list(ids),
                "workspace_id": workspace_id,
                "max_hops": _MAX_MERGE_HOPS,
            },
        )
    ).all()
    return {EntityId(row[0]): EntityId(row[1]) for row in rows}


async def contact_ids_for_account(
    conn: AsyncConnection, account_entity_id: EntityId, *, include_merged: bool = False
) -> tuple[EntityId, ...]:
    """The **live** (non-merged) contact entity ids under an account — the committee membership the
    VERIFICATION pass and the M12 handoff assembler iterate.

    Merged-loser contacts are excluded (``status = 'merged'``): a merge re-keys the loser's claims
    onto the survivor, which is itself returned, so the survivor's claims are covered exactly once.
    Read-only; ordered by ``id`` for deterministic iteration. Entities are not tenant-scoped (claims
    carry tenancy), so this takes no scope — like :func:`get_contact`.

    ``include_merged=True`` returns the losers too, for a caller that reads *claims* off these rows
    and redirects them itself (``surviving_ids``). A merge does not rewrite the loser's immutable
    claims, so a reader that skipped the loser row would lose every fact the survivor inherited."""
    merged_clause = "" if include_merged else "AND status <> CAST(:merged AS entity_status) "
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT id FROM contact_entity "
                    f"WHERE account_entity_id = :acct {merged_clause}"
                    "ORDER BY id"
                ),
                {"acct": account_entity_id}
                | ({} if include_merged else {"merged": AccountStatus.MERGED.value}),
            )
        )
        .scalars()
        .all()
    )
    return tuple(EntityId(r) for r in rows)


async def get_entity(
    conn: AsyncConnection, entity_id: EntityId, entity_type: EntityType
) -> AccountEntity | ContactEntity | None:
    """The typed entity record for ``(id, entity_type)`` — dispatches to account/contact."""
    if entity_type is EntityType.ACCOUNT:
        return await get_account(conn, entity_id)
    if entity_type is EntityType.CONTACT:
        return await get_contact(conn, entity_id)
    raise UnknownEntityTypeError(f"no entity table for entity_type {entity_type!r}")


async def resolve_alias(
    conn: AsyncConnection, key: str, entity_type: EntityType, *, workspace_id: str
) -> EntityId | None:
    """Exact strong-key / normalized-alias lookup → the **surviving** ``entity_id``, or ``None``.

    *Deterministic only* (substrate §2 stage 1): no fuzzy fallback (that is M2.2). For an account,
    ``key`` is tried as a registrable domain (against ``primary_domain``) and as a name-key (against
    the normalized ``aliases`` index); a domain hit wins. For a contact, ``key`` is tried against
    ``linkedin_url`` / ``verified_email`` and the alias index. A hit on a *merged* entity resolves
    through :func:`surviving_id` to the live survivor.

    ``workspace_id`` is **required** (accounts/contacts are workspace-local; founder ruling
    2026-07-22): every branch is scoped to it, so client A's exact-name lookup can never hit client
    B's account."""
    if entity_type is EntityType.ACCOUNT:
        domain = registrable_domain(key)
        if domain is not None:
            hit = (
                await conn.execute(
                    text(
                        "SELECT id FROM account_entity "
                        "WHERE primary_domain = :d AND workspace_id = :ws LIMIT 1"
                    ),
                    {"d": domain, "ws": workspace_id},
                )
            ).scalar()
            if hit is not None:
                return await surviving_id(conn, EntityId(hit), entity_type)
        nk = name_key(key)
        if nk:
            hit = (
                await conn.execute(
                    text(
                        "SELECT id FROM account_entity "
                        "WHERE :k = ANY(aliases) AND workspace_id = :ws LIMIT 1"
                    ),
                    {"k": nk, "ws": workspace_id},
                )
            ).scalar()
            if hit is not None:
                return await surviving_id(conn, EntityId(hit), entity_type)
        return None

    if entity_type is EntityType.CONTACT:
        strong = _normalize_strong_text(key)
        if strong is not None:
            hit = (
                await conn.execute(
                    text(
                        "SELECT id FROM contact_entity "
                        "WHERE (linkedin_url = :s OR verified_email = :s) "
                        "AND workspace_id = :ws LIMIT 1"
                    ),
                    {"s": strong, "ws": workspace_id},
                )
            ).scalar()
            if hit is not None:
                return await surviving_id(conn, EntityId(hit), entity_type)
        nk = name_key(key)
        if nk:
            hit = (
                await conn.execute(
                    text(
                        "SELECT id FROM contact_entity "
                        "WHERE :k = ANY(aliases) AND workspace_id = :ws LIMIT 1"
                    ),
                    {"k": nk, "ws": workspace_id},
                )
            ).scalar()
            if hit is not None:
                return await surviving_id(conn, EntityId(hit), entity_type)
        return None

    raise UnknownEntityTypeError(f"no entity table for entity_type {entity_type!r}")


async def surviving_id(
    conn: AsyncConnection, entity_id: EntityId, entity_type: EntityType
) -> EntityId:
    """Follow the ``merged_into`` chain to the live survivor in one call (union-find read).

    Returns ``entity_id`` itself when it is not merged (or unknown — a dangling id resolves to
    itself, not an error). Raises :class:`MergeCycleError` if the chain revisits an id (a cycle the
    no-self-merge CHECK cannot catch beyond one hop), so a corrupt chain errors rather than hangs.
    """
    table = _table(entity_type)
    stmt = text(f"SELECT merged_into FROM {table} WHERE id = :id")
    current = entity_id
    seen: set[EntityId] = {current}
    for _ in range(_MAX_MERGE_HOPS):
        nxt = (await conn.execute(stmt, {"id": current})).scalar()
        if nxt is None:
            return current
        nxt_id = EntityId(nxt)
        if nxt_id in seen:
            raise MergeCycleError(
                f"merged_into chain for {entity_type.value} {entity_id} cycles at {nxt_id}"
            )
        seen.add(nxt_id)
        current = nxt_id
    raise MergeCycleError(
        f"merged_into chain for {entity_type.value} {entity_id} exceeds {_MAX_MERGE_HOPS} hops"
    )
