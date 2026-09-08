"""FI-2 slice 1, Task 3 — the global-lens account detail: ``GET /frontend/v1/accounts/{id}``.

The **union** view of one account: everything the workspace knows about it, with every piece of
project-relative work attributed to the project that produced it (FI-2 §7 R2). It composes the same
untouched mechanism surfaces the list endpoint does, plus two more:

1. **identity** — the ``account_entity`` row (name/domain/aliases/registry ids/HQ), with
   ``surviving_id`` semantics: a merged loser is not a 404, it is a **redirect** — the survivor is
   served and ``redirectedFrom`` names the id the caller asked for;
2. **field species** — :func:`~clue_core.resolve_research_scope` over the *effective* registry
   (global + workspace rows) decides, per field this account actually holds claims for, whether it
   is workspace truth or per-project work. Nothing here enumerates field families: the split is a
   registry read, so a pack that later declares a relative field lands in the project sections
   automatically and a §5.2 re-ratification cannot silently drift from this endpoint;
3. **neutral facts** — the ``project_neutral`` half, served ONCE from ``current_values`` (the
   canonical merge) with its freshness state, reference time and producing source. Deliberately
   **not** lineage-filtered: a neutral fact is workspace truth in every lens, whichever project's
   run happened to pay for it (FI-2 slice-0 handoff — lineage filtering is species-conditional);
4. **project sections** — the ``project_relative`` half, partitioned by ``run_lineage.project_id``.
   A claim whose run has no lineage row, or a lineage row with a NULL project, goes to the
   **unattributed** section (``projectId: null``) rather than being dropped or guessed onto a
   project: the exemption classes are real (``run_lineage``'s module docstring lists them —
   redaction runs, pre-FI-2 rows) and hiding their claims would misreport the account. Each
   section's project ``name`` comes from ONE batched
   :func:`~clue_api.frontend_read.accounts_list.project_names` read shared with the list row;
5. **committee** — the union of every targeting project's governed committee, through
   ``ContactEligibilityResolver`` (never ``identity.contact_ids_for_account``, per the FI-1 §4.5
   ruling), each member carrying the projects that target them. Two gates, both the resolver's or
   C7's and neither re-derived here: *membership* eligibility is the resolver's (a member whose
   role/persona binding is not STRONG does not come back), and *display* eligibility is
   ``committee.committee_member_displayable`` over the workspace policy — the same gate the
   `/contacts` endpoints apply, shared so the two surfaces cannot answer differently about the same
   people;
6. **coverage** — how many fields this account actually holds, and which fields research asked for
   and could not resolve.

**Wire-shape deviations from the task plan, both for the same reason** (recorded here because
Task 5 copies the *as-built* shapes into `apps/frontend/docs/api-contracts/accounts.md`): the plan
sketches ``score: {...}|null`` and ``narrative: {...}|null``; this endpoint serves ``scores: [...]``
and ``narratives: [...]``. One project can legitimately score an account under several ICPs (D5)
and can hold one value narrative *per persona* (M12.1). Collapsing either to a single slot would
require picking a winner — the representative-run fiction FI-2 §7 exists to remove. Plural is the
honest shape; ``insights`` was already plural.

The two disciplines the list endpoint enforces hold here too, for the same reasons:

* **Never scope a claim read by ``claim.workspace_id``** — a DB CHECK forces it NULL on every
  ``public_footprint`` claim, so that predicate silently *empties* a read instead of narrowing it.
  Every claim read here scopes through the **entity** (an id already proven to belong to this
  workspace) plus ``WorkspaceScope.predicate()``, and the lineage join adds
  ``run_lineage.workspace_id`` — a real tenancy column on a real tenancy table.
* **Band-2 wire discipline** — semantic values only: enums, numbers, ISO-8601 timestamps, opaque
  ids, and ``null`` wherever the backend genuinely knows nothing. ``provider`` is the raw
  ``claim.source_key``: no source display-name surface exists anywhere in the platform
  (``SourceManifest`` carries no label, and the C7 provider chip renders the raw string too), and
  inventing a label map here would be exactly the presentation mapping Band-2 forbids.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import JsonValue
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.recipes import Page
from clue_api.client_context_binding import workspace_client_entity_id
from clue_api.frontend_read.accounts_list import (
    SCORE_FIELD_KEYS,
    V1_NEUTRAL_FIELD_KEYS,
    ProjectScore,
    WireModel,
    _primary_project_fit,
    _read_scores,
    as_int,
    as_str,
    group_score_claims,
    project_names,
)
from clue_api.frontend_read.app import ContractDep, WorkspaceDep
from clue_api.frontend_read.committee import read_governed_committee
from clue_api.frontend_read.contract_v1 import (
    AccountDetailResponseV1,
    AccountDetailV1,
    ResearchDisplayBlock,
)
from clue_api.frontend_read.display_pages import (
    DisplayPages,
    buying_committee,
    committee,
    rail_contacts,
)
from clue_api.frontend_read.evidence import (
    EvidenceReference,
    evidence_artifact_response,
    evidence_reference,
    live_artifact_claim_ids,
    read_live_artifact,
)
from clue_api.frontend_read.prose import ACCOUNT_SUMMARY_FIELD, ProseRead, read_prose
from clue_api.frontend_read.v1_shared import (
    EMPTY_BAND,
    RESEARCH_STATUS_LABELS,
    activity_for,
    arv2_research_status_for,
    custom_fields_for,
    employee_range_label,
    fit_band,
    fit_score_100,
    funding_label,
    headcount_label,
    industry_labels,
    iso_utc,
    last_modified_for,
    location_label,
    owners_for,
    research_evidence_for,
    revenue_label,
    socials,
    website_label,
    website_url,
)
from clue_config import Settings
from clue_core import (
    ClaimId,
    EntityId,
    EntityType,
    FreshnessState,
    Persona,
    ResearchScope,
    reference_time,
)
from clue_db import ConnFactory
from clue_research.claimstore import (
    FieldFilters,
    FieldRegistryScope,
    WorkspaceScope,
    active_merge_policy,
    claims_by_ids,
    current_values,
    # FI-2 P3's one species derivation, which now lives beside ``list_effective_fields`` in the
    # claim-store registry: the research economics (the account runtime's fresh-skip, the R5 guard,
    # the Sumble gap ladder) must answer "is this field project-relative?" exactly as this read
    # layer does, and a research-path module importing a BFF module was the wrong direction.
    field_species,
    list_effective_fields,
    merge_claims,
)
from clue_research.compliance import load_workspace_policy
from clue_research.identity import get_account, get_contacts, surviving_id
from clue_research.membership import ProjectMembership, memberships_for_accounts
from clue_storage import StorageBackend

#: ``account.value_narrative`` gets its own slot in a project section: it is the FI-2 §5.2 relative
#: family that is an *argument* rather than a fact, and the frontend renders it as prose, not as a
#: field row. Imported by key rather than from ``clue_research.narrative`` so this read layer takes
#: no dependency on the narrative package's internals.
NARRATIVE_FIELD_KEY = "account.value_narrative"


class AccountNotFound(LookupError):
    """No live account with that id is visible in this workspace."""


# --- the wire vocabulary ----------------------------------------------------------------------


class NeutralFact(WireModel):
    """One ``project_neutral`` field's current truth, from the canonical merge.

    ``freshness`` is semantic, not cosmetic: the merge never drops a stale winner, it labels it, so
    the frontend can show "we know this, and it is past its TTL" instead of silently implying
    currency. (The M1.2 merge only ever assigns ``fresh``/``stale``; ``expired`` is the M9.5
    retention disposition, which never wins a merge.)
    """

    field_key: str
    value: JsonValue
    freshness: FreshnessState
    observed_at: datetime
    provider: str | None = None
    evidence: EvidenceReference


class RelativeFact(WireModel):
    """One live ``project_relative`` claim, exactly as written — not merged.

    Relative claims are **not** collapsed to one winner per field: several are legitimate at once
    (one narrative per persona; one insight per aspect), and merging them would destroy precisely
    the per-project, per-persona structure this endpoint exists to expose.
    """

    field_key: str
    value: JsonValue
    observed_at: datetime
    provider: str | None = None
    evidence: EvidenceReference


class AccountProjectSection(WireModel):
    """One project's work on this account — or, when ``project_id`` is ``null``, the honest
    **unattributed** bucket for claims whose run maps to no project.

    ``added_via``/``added_at`` come from ``project_account`` and are ``null`` in two legitimate
    cases: the unattributed section (no membership exists to describe), and a project that produced
    research on this account without a membership row — which should not happen, and is therefore
    reported rather than hidden.

    ``name`` is the ``project`` row's own name, from the same batched
    :func:`~clue_api.frontend_read.accounts_list.project_names` read the list row uses, so the two
    surfaces cannot name one project differently. It is ``null`` for the unattributed section (there
    is no project to name) and for a lineage-derived project id this workspace holds no ``project``
    row for — ``run_lineage.project_id`` carries no FK to ``project``, so that is reachable, and an
    unnamed section is the honest rendering of it.
    """

    project_id: str | None = None
    name: str | None = None
    added_via: str | None = None
    added_at: datetime | None = None
    scores: tuple[ProjectScore, ...] = ()
    narratives: tuple[RelativeFact, ...] = ()
    insights: tuple[RelativeFact, ...] = ()


class CommitteeMemberRow(WireModel):
    """One governed committee member, with the projects that target them."""

    contact_id: uuid.UUID
    name: str | None = None
    persona: Persona
    role_on_committee: str
    project_ids: tuple[str, ...] = ()


class UnresolvedField(WireModel):
    """A research gap plus the registry-authored explanation of what was requested."""

    field_key: str
    description: str | None = None


class AccountCoverage(WireModel):
    """How much of this account is actually researched — a confidence report, not a guarantee.

    ``researched_field_count`` counts the distinct fields holding at least one live, non-rejected
    claim for this account: the honest "how much do we hold". ``unresolved_field_keys`` are fields
    the M8D research surface *asked for* and could not answer (``null``/``unsupported`` outcomes)
    and that still hold no live claim — an empty, flagged field is a correct output, and naming it
    is more useful than a percentage that implies exhaustiveness the platform cannot prove.
    """

    researched_field_count: int
    unresolved_field_keys: tuple[str, ...] = ()
    unresolved_fields: tuple[UnresolvedField, ...] = ()


class AccountDetail(WireModel):
    """The whole account, unioned across projects."""

    id: uuid.UUID
    name: str
    domain: str | None = None
    aliases: tuple[str, ...] = ()
    registry_ids: dict[str, str] = {}
    hq_geo: dict[str, JsonValue] | None = None
    # Set when the requested id was a merged loser: the body is the survivor's, and this names what
    # the caller asked for so a bookmarked/linked id resolves visibly rather than silently.
    redirected_from: uuid.UUID | None = None
    summary: ProseRead
    neutral_facts: tuple[NeutralFact, ...] = ()
    project_sections: tuple[AccountProjectSection, ...] = ()
    committee: tuple[CommitteeMemberRow, ...] = ()
    coverage: AccountCoverage


# --- SQL --------------------------------------------------------------------------------------

# Every field this account holds a live, promotable claim for. Eligibility mirrors the merge's
# (live, field-flavoured, not rejected) so the key set and the values agree. Scoped through the
# entity — the id is already proven to be this workspace's — plus the reuse-class predicate.
_DISTINCT_FIELD_KEYS_TEMPLATE = """
    SELECT DISTINCT field_key
    FROM claim
    WHERE entity_id = :entity_id
      AND superseded_by IS NULL
      AND claim_flavor = 'field_claim'
      AND verification_status <> 'rejected'
      AND {scope_sql}
"""

# The relative half, with its project attribution. A **LEFT** join (unlike the list endpoint's
# inner join): a claim whose run has no lineage row, or whose lineage row carries no project, must
# reach the unattributed section rather than disappear. The join is qualified by workspace so a
# lineage row belonging to another tenant can never attribute this workspace's claim, and it
# dispatches on ``project_id`` alone — ``run_lineage.kind`` is advisory, first-writer-wins metadata
# over a mixed run-id space and must never decide attribution (FI-2 slice-0 handoff).
RELATIVE_CLAIMS_TEMPLATE = """
    SELECT c.id, l.project_id
    FROM (
        SELECT id, run_id, collected_at
        FROM claim
        WHERE entity_id = :entity_id
          AND field_key IN :field_keys
          AND superseded_by IS NULL
          AND claim_flavor = 'field_claim'
          AND verification_status <> 'rejected'
          AND {scope_sql}
    ) c
    LEFT JOIN run_lineage l
        ON l.run_id = c.run_id AND l.workspace_id = :lineage_workspace_id
    ORDER BY c.collected_at, c.id
"""

# Fields the M8D research surface asked for and could not answer. The result *row* is reached
# through ``entity_research_result_subject_history (workspace_id, target_entity_id, …)``, but the
# subject filter that decides the answer is the **field row's own**: an account result carries the
# fields of every contact it discovered (``entity_research_tools._flatten_result_fields`` persists
# ``discovered_subjects``' fields under the account's result, stamping each row's own
# ``subject_type``/``target_entity_id``). Filtering on the result alone would therefore report a
# *contact's* unresolved field as the account's — and it could never clear, because answering it
# writes a contact claim this account's held-key set never sees.
_UNRESOLVED_FIELDS = text(
    """
    SELECT DISTINCT f.field_key
    FROM entity_research_result r
    JOIN entity_research_result_field f ON f.result_id = r.result_id
    WHERE r.workspace_id = :workspace_id
      AND r.target_entity_id = :entity_id
      AND f.workspace_id = :workspace_id
      AND f.subject_type = 'account'
      AND f.target_entity_id = :entity_id
      AND f.outcome IN ('null', 'unsupported')
    """
)

# --- composition helpers ----------------------------------------------------------------------


async def _read_distinct_field_keys(
    conn: AsyncConnection, *, entity_id: EntityId, scope: WorkspaceScope
) -> tuple[str, ...]:
    scope_sql, scope_params = scope.predicate()
    rows = await conn.execute(
        text(_DISTINCT_FIELD_KEYS_TEMPLATE.format(scope_sql=scope_sql)),
        {"entity_id": entity_id, **scope_params},
    )
    return tuple(sorted(str(key) for key in rows.scalars()))


async def _read_neutral_facts(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    field_keys: Sequence[str],
    scope: WorkspaceScope,
) -> tuple[NeutralFact, ...]:
    """The canonical merge over the neutral fields, enriched with the winning claim's source.

    ``CurrentValue.provenance`` carries the winning claim's id but neither its ``source_key`` nor
    its ``observed_at``, so the winners are re-read in one batch — the same claims, by id, under the
    same scope.
    """
    if not field_keys:
        return ()
    merged = await current_values(conn, [entity_id], field_keys, scope=scope)
    if not merged:
        return ()
    winners = await claims_by_ids(
        conn, [value.provenance.claim_id for value in merged.values()], scope=scope
    )
    artifact_claim_ids = await live_artifact_claim_ids(
        conn, claims=winners.values(), workspace_id=scope.workspace_id or ""
    )
    facts: list[NeutralFact] = []
    for (_entity, field_key), value in merged.items():
        winner = winners.get(value.provenance.claim_id)
        if winner is None:
            continue
        facts.append(
            NeutralFact(
                field_key=field_key,
                value=value.value_json,
                freshness=value.freshness_state,
                observed_at=reference_time(winner),
                provider=winner.source_key,
                evidence=evidence_reference(
                    winner,
                    freshness=value.freshness_state,
                    artifact_available=str(winner.id) in artifact_claim_ids,
                ),
            )
        )
    return tuple(sorted(facts, key=lambda fact: fact.field_key))


class _RelativeClaims:
    """The relative half, already partitioned by project (``None`` = unattributed)."""

    def __init__(self) -> None:
        self.scores: dict[str | None, tuple[ProjectScore, ...]] = {}
        self.narratives: dict[str | None, list[RelativeFact]] = defaultdict(list)
        self.insights: dict[str | None, list[RelativeFact]] = defaultdict(list)

    @property
    def projects(self) -> set[str | None]:
        return set(self.scores) | set(self.narratives) | set(self.insights)


async def _read_relative_claims(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    field_keys: Sequence[str],
    workspace_id: str,
    scope: WorkspaceScope,
) -> _RelativeClaims:
    """Read every live relative claim and route it by *species-derived* family.

    Three families, and the routing is derived from the field key's registered species rather than
    from an enumerated list of "insight" fields — which matters because the FI-1-era insight
    families (``account.recent_funding``, ``operational_pain``, ``strategic_moves``,
    ``account.resonance.*``) are all ``project_neutral`` under the ratified §5.2 table and belong in
    ``neutralFacts``. ``insights`` therefore means "a relative field that is neither a score nor the
    narrative" — today only a pack field that declares itself relative, tomorrow whatever §5.2
    ratifies next, with no code change here.
    """
    partitioned = _RelativeClaims()
    if not field_keys:
        return partitioned
    scope_sql, scope_params = scope.predicate()
    stmt = text(RELATIVE_CLAIMS_TEMPLATE.format(scope_sql=scope_sql)).bindparams(
        bindparam("field_keys", expanding=True)
    )
    rows = (
        await conn.execute(
            stmt,
            {
                "entity_id": entity_id,
                "field_keys": list(field_keys),
                "lineage_workspace_id": workspace_id,
                **scope_params,
            },
        )
    ).all()

    claim_ids = [row[0] for row in rows]
    claims = await claims_by_ids(conn, claim_ids, scope=scope)
    artifact_claim_ids = await live_artifact_claim_ids(
        conn, claims=claims.values(), workspace_id=workspace_id
    )
    definitions = {
        str(item.field_def.field_key): item.field_def
        for item in await list_effective_fields(
            conn,
            scope=FieldRegistryScope.for_workspace(workspace_id),
            filters=FieldFilters(active=None),
            include_retired=True,
        )
    }
    now = datetime.now(UTC)
    policy = active_merge_policy()

    score_rows: list[tuple[uuid.UUID, str | None, str, Any, datetime]] = []
    for claim_id, project_id in rows:
        claim = claims.get(claim_id)
        if claim is None:
            continue
        key = str(claim.field_key)
        value = claim.value_json
        project = None if project_id is None else str(project_id)
        at = reference_time(claim)
        if key in SCORE_FIELD_KEYS:
            score_rows.append((uuid.UUID(str(entity_id)), project, key, value, at))
            continue
        definition = definitions.get(key)
        current = merge_claims(
            (claim,),
            None if definition is None else definition.freshness_ttl,
            policy,
            now,
        )
        fact = RelativeFact(
            field_key=key,
            value=value,
            observed_at=at,
            provider=claim.source_key,
            evidence=evidence_reference(
                claim,
                freshness=None if current is None else current.freshness_state,
                artifact_available=str(claim.id) in artifact_claim_ids,
            ),
        )
        target = partitioned.narratives if key == NARRATIVE_FIELD_KEY else partitioned.insights
        target[project].append(fact)

    partitioned.scores = {
        project: scores for (_entity, project), scores in group_score_claims(score_rows).items()
    }
    return partitioned


async def _read_committee(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    workspace_id: str,
    memberships: Sequence[ProjectMembership],
) -> tuple[CommitteeMemberRow, ...]:
    """Project the shared governed committee into Account-detail rows.

    Addressability is not re-derived here: the Contacts list and Contact profile consume the same
    :func:`read_governed_committee` result, so every member linked from this response is a valid
    Contact-detail subject under the same workspace policy.
    """
    union, _policy = await read_governed_committee(
        conn,
        account_id=account_id,
        workspace_id=workspace_id,
        memberships=memberships,
    )
    if not union.members:
        return ()
    contacts = await get_contacts(conn, tuple(union.members))
    return tuple(
        sorted(
            (
                CommitteeMemberRow(
                    contact_id=uuid.UUID(str(contact_id)),
                    name=contacts[contact_id].full_name if contact_id in contacts else None,
                    persona=member.persona,
                    role_on_committee=member.role_on_committee,
                    project_ids=tuple(union.project_ids[contact_id]),
                )
                for contact_id, member in union.members.items()
            ),
            key=lambda member: (member.persona.value, str(member.contact_id)),
        )
    )


async def _read_coverage(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    workspace_id: str,
    held_field_keys: Sequence[str],
) -> AccountCoverage:
    rows = await conn.execute(
        _UNRESOLVED_FIELDS, {"workspace_id": workspace_id, "entity_id": entity_id}
    )
    held = set(held_field_keys)
    # A field research once failed on but has since been answered is not unresolved.
    unresolved = sorted({str(key) for key in rows.scalars()} - held)
    definitions = (
        {
            item.field_def.field_key: item
            for item in await list_effective_fields(
                conn,
                scope=FieldRegistryScope.for_workspace(workspace_id),
                filters=FieldFilters(active=None),
                include_retired=True,
            )
        }
        if unresolved
        else {}
    )
    return AccountCoverage(
        researched_field_count=len(held),
        unresolved_field_keys=tuple(unresolved),
        unresolved_fields=tuple(
            UnresolvedField(
                field_key=field_key,
                description=(
                    definitions[field_key].description if field_key in definitions else None
                ),
            )
            for field_key in unresolved
        ),
    )


def _sections(
    memberships: Sequence[ProjectMembership],
    relative: _RelativeClaims,
    names: dict[str, str],
) -> tuple[AccountProjectSection, ...]:
    """One section per targeting project, plus any project that produced relative work without a
    membership row, plus the unattributed bucket when (and only when) it has something in it.

    A project with a membership but no relative work still gets a section: "this project targets
    this account and has produced nothing yet" is a real, useful state, and rendering it as absence
    would be indistinguishable from the account not being targeted at all.
    """
    membership_by_project = {membership.project_id: membership for membership in memberships}
    ordered: list[str | None] = [membership.project_id for membership in memberships]
    ordered += sorted(
        project
        for project in relative.projects
        if project is not None and project not in membership_by_project
    )
    if None in relative.projects:
        # Always last: it is a residue bucket, not a peer of the real projects.
        ordered.append(None)

    sections: list[AccountProjectSection] = []
    for project in ordered:
        membership = membership_by_project.get(project) if project is not None else None
        sections.append(
            AccountProjectSection(
                project_id=project,
                name=None if project is None else names.get(project),
                added_via=None if membership is None else membership.added_via,
                added_at=None if membership is None else membership.added_at,
                scores=relative.scores.get(project, ()),
                narratives=tuple(relative.narratives.get(project, ())),
                insights=tuple(relative.insights.get(project, ())),
            )
        )
    return tuple(sections)


# --- the read model ---------------------------------------------------------------------------


async def read_account_detail(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
) -> AccountDetail:
    """The union detail for one account, or :class:`AccountNotFound`.

    A merged loser is followed to its survivor and served with ``redirected_from`` set — matching
    ``surviving_id`` semantics, and matching what a user expects from a bookmarked id after a
    dedup. An id that is unknown, or that belongs to another workspace, is
    :class:`AccountNotFound` — the two are deliberately indistinguishable to the caller, so the
    endpoint cannot be used to probe another tenant's id space.
    """
    requested = EntityId(account_id)
    canonical = await surviving_id(conn, requested, EntityType.ACCOUNT)
    account = await get_account(conn, canonical)
    client_entity_id = await workspace_client_entity_id(conn, workspace_id=workspace_id)
    if account is None or account.workspace_id != workspace_id or canonical == client_entity_id:
        raise AccountNotFound(str(account_id))

    scope = WorkspaceScope.for_workspace(workspace_id)
    field_keys = await _read_distinct_field_keys(conn, entity_id=canonical, scope=scope)
    fact_keys = tuple(key for key in field_keys if key != ACCOUNT_SUMMARY_FIELD)
    species = await field_species(conn, workspace_id=workspace_id, field_keys=fact_keys)
    neutral_keys = [key for key in fact_keys if species[key] is ResearchScope.PROJECT_NEUTRAL]
    relative_keys = [key for key in fact_keys if species[key] is ResearchScope.PROJECT_RELATIVE]

    memberships = (
        await memberships_for_accounts(
            conn, workspace_id=workspace_id, account_ids=[uuid.UUID(str(canonical))]
        )
    ).get(uuid.UUID(str(canonical)), ())

    neutral_facts = await _read_neutral_facts(
        conn, entity_id=canonical, field_keys=neutral_keys, scope=scope
    )
    summary = await read_prose(
        conn,
        entity_id=canonical,
        field_key=ACCOUNT_SUMMARY_FIELD,
        scope=scope,
    )
    relative = await _read_relative_claims(
        conn,
        entity_id=canonical,
        field_keys=relative_keys,
        workspace_id=workspace_id,
        scope=scope,
    )
    committee = await _read_committee(
        conn,
        account_id=canonical,
        workspace_id=workspace_id,
        memberships=memberships,
    )
    coverage = await _read_coverage(
        conn, entity_id=canonical, workspace_id=workspace_id, held_field_keys=field_keys
    )
    # One batched read over every project this response will show a section for — the membership
    # projects plus the lineage-derived ones — so section names cost one statement, not one each.
    names = await project_names(
        conn,
        workspace_id=workspace_id,
        project_ids=[membership.project_id for membership in memberships] + list(relative.projects),
    )

    return AccountDetail(
        id=uuid.UUID(str(canonical)),
        name=account.canonical_name,
        domain=account.primary_domain,
        aliases=account.aliases,
        registry_ids=account.registry_ids,
        hq_geo=account.hq_geo,
        redirected_from=None if canonical == requested else account_id,
        summary=summary,
        neutral_facts=neutral_facts,
        project_sections=_sections(memberships, relative, names),
        committee=committee,
        coverage=coverage,
    )


# --- contract v1 (ARV2 D3, E2) ----------------------------------------------------------------

#: The neutral fields the **contract-v1 detail** renders, read in ONE batched merge. A superset of
#: the v1 *list* row's set (:data:`~clue_api.frontend_read.accounts_list.V1_NEUTRAL_FIELD_KEYS`,
#: imported rather than restated so the two screens can never disagree about the account's chrome)
#: plus the four the detail's rail adds: revenue, founding year, and the two funding facts.
V1_DETAIL_FIELD_KEYS: tuple[str, ...] = (
    *V1_NEUTRAL_FIELD_KEYS,
    "core.annual_revenue",
    "core.founded_year",
    "account.recent_funding",
    "account.total_funding",
)

#: The page the account detail serves. Named so the reader and the evidence route cannot drift.
OVERVIEW_PAGE: Page = "overview"


def founded_label(value: Any) -> str | None:
    """``core.founded_year`` as the year a screen shows, or ``None`` when it is not a year.

    A year is an integer. The claim may arrive as one, as a float that *is* one, or — through the
    D1 lenient writer, which stores what the provider returned rather than what the registry
    declares — as the string ``"2022"``. Anything else (``"founded in the nineties"``, an object)
    yields ``None`` and the label is omitted: an unparseable year is not a year, and printing the
    raw value would put prose in a rail slot that the frontend renders as a date.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else None
    if isinstance(value, str):
        try:
            return str(int(value.strip()))
        except ValueError:
            return None
    return None


# The one account's own spine row. Not the list's ``_ACCOUNT_PEOPLE`` read: this branch needs the
# two timestamps as well (``createdAt`` is required in contract v1 and the entity model does not
# carry them), and widening a shared statement for one caller is how a batched read for a page
# quietly becomes a wider read for every row of it.
_ACCOUNT_SPINE = text(
    """
    SELECT owner_user_id, created_by_user_id, created_at, updated_at
    FROM account_entity
    WHERE workspace_id = :workspace_id AND id = :entity_id
    """
)


async def read_account_detail_v1(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
    display: DisplayPages,
    settings: Settings,
    now: datetime,
) -> AccountDetailResponseV1:
    """The account detail in **contract v1** — the ARV2 account page and its preview.

    Same account, same resolution rules as :func:`read_account_detail` (``surviving_id``, the
    workspace check, the client-entity exclusion, the same :class:`AccountNotFound`); what differs
    is everything served. The v1 detail is the *screen's* detail: the rail's labels, the account's
    own chrome, the committee card, the generated overview page, and the evidence behind every
    citation on it.

    A merged loser is followed **silently** — the contract has no ``redirectedFrom`` slot, so the
    survivor is simply served rather than a field being invented to announce the redirect.

    Two properties are structural rather than incidental:

    * **the fit and the research status are the primary project's**, exactly as the v1 list row's
      are, because the page has one of each. An account with no membership has no project to
      report a status for and is honestly ``not_started``, never attributed to whichever project
      happened to research it;
    * **the evidence drawer is the union of what the page cites and what the committee card
      shows.** A committee email chip finds its evidence by claim id (ruling R5), so an
      ``emailClaimId`` with no row in ``researchEvidence`` would be a chip that opens onto
      nothing.

    Every source is read in a fixed number of batched statements: a per-member or per-field lookup
    here is what the suite's v1 statement-count guard exists to prevent.
    """
    requested = EntityId(account_id)
    canonical = await surviving_id(conn, requested, EntityType.ACCOUNT)
    account = await get_account(conn, canonical)
    client_entity_id = await workspace_client_entity_id(conn, workspace_id=workspace_id)
    if account is None or account.workspace_id != workspace_id or canonical == client_entity_id:
        raise AccountNotFound(str(account_id))

    account_uuid = uuid.UUID(str(canonical))
    scope = WorkspaceScope.for_workspace(workspace_id)
    neutral = await current_values(conn, [canonical], V1_DETAIL_FIELD_KEYS, scope=scope)

    def value_of(field_key: str) -> Any:
        current = neutral.get((canonical, field_key))
        return None if current is None else current.value_json

    memberships = (
        await memberships_for_accounts(conn, workspace_id=workspace_id, account_ids=[account_uuid])
    ).get(account_uuid, ())
    # The recorded FI-2 §2 policy: element 0 of the membership read is the primary project.
    primary_project_id = memberships[0].project_id if memberships else None

    scores = await _read_scores(conn, workspace_id=workspace_id, entity_ids=[account_uuid])
    # The v1 *list* row's research read, shared rather than re-written so the table and the page
    # can never report a different status for one account. Its refresh flag is dropped here: the
    # detail contract has no ``researchIsRefreshing`` slot (the Zod schema is the arbiter of that
    # split), and a second query for the status alone is how the two surfaces would start to drift.
    research = await arv2_research_status_for(
        conn, workspace_id=workspace_id, account_ids=[canonical]
    )
    status, _refreshing = research.get(canonical, ("not_started", False))

    spine = (
        await conn.execute(_ACCOUNT_SPINE, {"workspace_id": workspace_id, "entity_id": canonical})
    ).one()
    owner_user_id, created_by_user_id, created_at, updated_at = spine
    owners = await owners_for(
        conn, user_ids=[user_id for user_id in (owner_user_id, created_by_user_id) if user_id]
    )
    custom_fields = await custom_fields_for(
        conn, workspace_id=workspace_id, account_ids=[canonical]
    )
    last_modified = await last_modified_for(
        conn, workspace_id=workspace_id, account_ids=[canonical]
    )

    policy = await load_workspace_policy(conn, workspace_id=workspace_id)
    members = await committee(conn, workspace_id=workspace_id, account_id=str(canonical))
    contacts = await rail_contacts(conn, workspace_id=workspace_id, members=members, policy=policy)
    committee_rows = await buying_committee(
        conn,
        workspace_id=workspace_id,
        account_id=str(canonical),
        members=members,
        policy=policy,
    )
    page = await display.page(
        conn,
        workspace_id=workspace_id,
        subject_kind="account",
        subject_id=str(canonical),
        page=OVERVIEW_PAGE,
    )
    activity = await activity_for(conn, workspace_id=workspace_id, account_id=canonical, now=now)
    # The drawer's ids: what the page cites, then what the committee's email chips point at,
    # deduped in that order (``dict.fromkeys`` is order-preserving) so an id cited by both appears
    # once and the page's own order leads.
    evidence = await research_evidence_for(
        conn,
        workspace_id=workspace_id,
        claim_ids=dict.fromkeys(
            (
                *page.cited_claim_ids,
                *(row.email_claim_id for row in committee_rows if row.email_claim_id),
            )
        ),
    )

    # ``canonical_name`` is NOT NULL on the spine, but a blank one would fail the contract's
    # ``min(1)``; the domain, then the id, keep the page honest and reachable.
    name = str(account.canonical_name or account.primary_domain or account_uuid)
    location = location_label(value_of("core.hq_location"))
    fit = _primary_project_fit(scores.get(account_uuid, ()), primary_project_id)
    return AccountDetailResponseV1(
        data=AccountDetailV1(
            id=str(account_uuid),
            name=name,
            # The preview and the page are the same subject; the dummy renders the two slots from
            # different fields, and serving anything but the account's name in one of them would
            # be a second name for one account.
            preview_title=name,
            # No logo pipeline exists (D0 ruling S2): explicitly null, never a guessed URL.
            logo_path=None,
            website_url=website_url(account.primary_domain),
            website_label=website_label(account.primary_domain) or EMPTY_BAND,
            research_status=status,
            research_status_label=RESEARCH_STATUS_LABELS[status],
            owner=owners.get(owner_user_id) if owner_user_id else None,
            created_by=owners.get(created_by_user_id) if created_by_user_id else None,
            industry_labels=tuple(
                industry_labels(value_of("core.industry"), value_of("core.industries_all"))
            ),
            headcount_label=headcount_label(
                as_int(value_of("core.employee_count")),
                employee_range_label(value_of("core.employee_range")),
            ),
            # Required non-empty here (the list row may omit it), so an account with no location
            # says "Unknown" rather than dropping the rail row entirely.
            locations_label=location or EMPTY_BAND,
            revenue_label=revenue_label(
                value_of("core.annual_revenue"), as_str(value_of("core.revenue_band"))
            ),
            founded_label=founded_label(value_of("core.founded_year")),
            funding_label=funding_label(
                value_of("account.recent_funding"), value_of("account.total_funding")
            ),
            fit_score=fit_score_100(fit),
            # Omitted: the band IS the label the header shows, and a second rendering of one score
            # is a second place for the two to disagree.
            fit_score_label=None,
            overall_fit=fit_band(fit, settings=settings),
            created_at=iso_utc(created_at),
            last_modified_at=iso_utc(last_modified.get(canonical, updated_at)),
            socials=tuple(
                socials(value_of("core.company_linkedin_url"), value_of("core.company_twitter_url"))
            ),
            custom_fields=tuple(custom_fields.get(canonical, ())),
            # The four slots the display layer replaced. Served as empty lists, not omitted: the
            # contract requires them, and "this page has none" is the honest answer while the
            # dummy's legacy prose/criteria/insight surfaces have no backend owner (D0 rulings
            # S5/S9). ``overviewDisplay`` is where this account's prose actually lives.
            summary_paragraphs=(),
            business_paragraphs=(),
            header_metadata=(),
            fit_criteria=(),
            insights=(),
            contacts=tuple(contacts),
            activity=tuple(activity),
            research_evidence=tuple(evidence),
            # Always present, even when every section is empty: an all-empty block is still a
            # block, and the frontend renders the page grammar from it.
            overview_display=ResearchDisplayBlock.model_validate(page.display_block),
            buying_committee=tuple(committee_rows),
        )
    )


# --- the route --------------------------------------------------------------------------------


def register_account_detail_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    settings: Settings,
    display: DisplayPages,
    evidence_storage: StorageBackend | None = None,
) -> None:
    """Register ``GET /accounts/{account_id}`` on the workspace-scoped `/frontend/v1` router.

    One route, two contracts (the D3 ruling): ``?contract=v1`` selects the ARV2 detail, its
    absence keeps the FI-2 payload byte-for-byte. ``display`` is the D3 display seam the
    composition root shares across every endpoint that serves a generated page — one instance, so
    two screens looking at the same account schedule one rewrite between them — and ``settings``
    reaches the v1 branch because the fit bands are configured thresholds, not code (ruling S3).
    """

    @router.get("/accounts/{account_id}")
    async def get_account_detail(
        workspace_id: WorkspaceDep, account_id: uuid.UUID, mode: ContractDep
    ) -> AccountDetail | AccountDetailResponseV1:
        async with conn_factory() as conn:
            try:
                if mode == "v1":
                    return await read_account_detail_v1(
                        conn,
                        workspace_id=workspace_id,
                        account_id=account_id,
                        display=display,
                        settings=settings,
                        now=datetime.now(UTC),
                    )
                return await read_account_detail(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                )
            except AccountNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "ACCOUNT_NOT_FOUND",
                        "message": "no such account in this workspace",
                    },
                ) from exc

    @router.get("/accounts/{account_id}/evidence/{claim_id}")
    async def get_account_evidence_artifact(
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
        claim_id: uuid.UUID,
    ) -> Response:
        """Stream retained evidence only when the current Account read actually exposes it.

        "The current Account read" is the **union** of both contracts while both are served: the
        FI-2 body's ``neutralFacts``/``projectSections`` evidence, and the claim ids the v1
        overview page cites. The two expose genuinely different sets — the FI-2 body names no
        contact claim at all, and an overview section legitimately speaks about the committee — so
        authorising against one of them would make an evidence chip the ARV2 page renders open
        onto a 404. The v1 half is consulted only after the FI-2 half declines, so an FI-2-only
        deployment pays nothing for it — and it is consulted with ``generate=False``, so
        authorising a request can neither write a page nor schedule one.
        """

        if evidence_storage is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "EVIDENCE_SERVICE_UNAVAILABLE",
                    "message": "retained evidence is temporarily unavailable",
                },
            )
        async with conn_factory() as conn:
            try:
                detail = await read_account_detail(
                    conn, workspace_id=workspace_id, account_id=account_id
                )
            except AccountNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "EVIDENCE_NOT_FOUND",
                        "message": "no such evidence in this workspace",
                    },
                ) from exc
            references = [fact.evidence for fact in detail.neutral_facts]
            references.extend(
                fact.evidence
                for section in detail.project_sections
                for fact in (*section.narratives, *section.insights)
            )
            authorized = any(
                reference.claim_id == str(claim_id) and reference.protected_artifact_available
                for reference in references
            )
            if not authorized:
                # ``detail.id`` is the survivor, so a merged-loser url authorises against the page
                # the caller would actually be looking at. ``generate=False`` is load-bearing: an
                # authorisation check must never be a spend path, so this asks only what the
                # **stored** blocks cite and neither writes a section nor schedules a rewrite.
                page = await display.page(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind="account",
                    subject_id=str(detail.id),
                    page=OVERVIEW_PAGE,
                    generate=False,
                )
                authorized = str(claim_id) in page.cited_claim_ids
            if not authorized:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "EVIDENCE_NOT_FOUND",
                        "message": "no such evidence in this workspace",
                    },
                )
            typed_claim_id = ClaimId(claim_id)
            claims = await claims_by_ids(
                conn,
                (typed_claim_id,),
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            claim = claims.get(typed_claim_id)
            if claim is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "EVIDENCE_NOT_FOUND",
                        "message": "no such evidence in this workspace",
                    },
                )
            artifact = await read_live_artifact(
                conn,
                claim=claim,
                workspace_id=workspace_id,
                storage=evidence_storage,
            )
            if artifact is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "EVIDENCE_NOT_FOUND",
                        "message": "no such evidence in this workspace",
                    },
                )
            return evidence_artifact_response(artifact)
