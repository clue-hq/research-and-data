"""The resolution engine — deduplicate → record-link → canonicalize (M2.2).

The standard entity-resolution pipeline substrate §2 prescribes, with its non-negotiable ordering:
**deterministic first, probabilistic second.** An exact strong-key hit (domain / registry id for an
account; LinkedIn URL / verified email for a contact) auto-resolves at score ``1.0`` with *no model
call*; only on a miss does the resolver embed the name, pgvector-ANN + trigram/alias-block a bounded
candidate set, and run a policy-as-data pairwise scorer.

The single seam every caller uses is :func:`resolve` / :func:`resolve_many`, returning a
:class:`ResolutionResult` (ranked candidate ids + calibrated scores + the method taken). **M2.2
produces candidates + scores; it does not decide merges** — that disposition is M2.3, on its own
seam. The matcher behind this seam is hot-swappable: the embedder (:class:`Embedder`) and the scorer
weights (:class:`ResolutionPolicy`) are both injected, so replacing the heuristic with a learned
model is a config/implementation change invisible to discovery / import / committee callers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import ARRAY, Text, bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import EntityId, EntityType, decode_jsonb
from clue_research.identity.embedding import (
    DEFAULT_EMBEDDER,
    Embedder,
    vector_literal,
)
from clue_research.identity.entities import surviving_id
from clue_research.identity.normalize import (
    canonical_registry_id,
    name_key,
    registrable_domain,
)
from clue_research.identity.policy import DEFAULT_RESOLUTION_POLICY, ResolutionPolicy


class ResolutionMethod(StrEnum):
    """How a result was produced. ``DETERMINISTIC`` = an exact strong-key hit (no model call);
    ``PROBABILISTIC`` = the fuzzy candidate-gen + scorer path; ``NONE`` = nothing ran (a garbage
    bulk row that errored, surfaced rather than thrown)."""

    DETERMINISTIC = "deterministic"
    PROBABILISTIC = "probabilistic"
    NONE = "none"


class Observation(BaseModel):
    """The **input** to :func:`resolve` — a messy, unresolved row (import, discovery, committee).

    Carries whatever identifiers the caller has (name, domain, geo, strong keys for contacts).
    The engine first tries deterministic strong-key lookup; on a miss it embeds the name, blocks
    DB candidates, and scores each as ``Observation`` (left) vs :class:`_CandidateRecord` (right)
    → :class:`Candidate` (ranked output). Not a persisted entity — free-text in, entity ids out."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = ""
    entity_type: EntityType = EntityType.ACCOUNT
    domain: str | None = None
    registry_ids: dict[str, str] = {}
    geo: dict[str, JsonValue] | None = None
    aliases: tuple[str, ...] = ()
    linkedin_url: str | None = None  # contact strong key
    verified_email: str | None = None  # contact strong key


class Candidate(BaseModel):
    """One ranked candidate: the entity id, its calibrated score, and its feature breakdown."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    score: float
    features: dict[str, float] = {}


class ResolutionResult(BaseModel):
    """The ranked candidate set for one observation + the method taken and the top score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: ResolutionMethod
    candidates: tuple[Candidate, ...] = ()
    top_score: float = 0.0

    @property
    def top(self) -> Candidate | None:
        """The best candidate, or ``None`` when nothing matched."""
        return self.candidates[0] if self.candidates else None


# --- feature helpers (pure) -------------------------------------------------
def _geo_country(geo: Mapping[str, object] | None) -> str | None:
    """Normalize a country token from a geo dict (``country`` / ``country_code`` keys)."""
    if not geo:
        return None
    for key in ("country", "country_code", "Country"):
        value = geo.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _geo_agreement(
    obs_geo: Mapping[str, object] | None, cand_geo: Mapping[str, object] | None
) -> float:
    """Pairwise geo feature for :func:`_score`: ``1.0`` match, ``0.0`` mismatch, ``0.5`` if either side
    lacks a country (neutral — does not penalize unknown geo)."""
    obs_country, cand_country = _geo_country(obs_geo), _geo_country(cand_geo)
    if obs_country is None or cand_country is None:
        return 0.5  # neutral — one side unknown
    return 1.0 if obs_country == cand_country else 0.0


def _token_jaccard(a: set[str], b: set[str]) -> float:
    """Token-set Jaccard similarity: ``|a ∩ b| / |a ∪ b|``; ``0.0`` when either set is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _name_jaccard(obs_name: str, candidate_aliases: Sequence[str]) -> float:
    """Best token-Jaccard of the observation name-key against any of the candidate's match-keys."""
    obs_tokens = set(name_key(obs_name).split())
    if not obs_tokens:
        return 0.0
    return max((_token_jaccard(obs_tokens, set(a.split())) for a in candidate_aliases), default=0.0)


def _alias_overlap(obs_aliases: Sequence[str], candidate_aliases: Sequence[str]) -> float:
    """Share of the observation's normalized alias keys that appear on the candidate (``0.0``–``1.0``)."""
    obs_keys = {name_key(a) for a in obs_aliases if name_key(a)}
    if not obs_keys:
        return 0.0
    return len(obs_keys & set(candidate_aliases)) / len(obs_keys)


def _domain_agreement(obs: Observation, cand_domain: str | None) -> float:
    """``1.0`` when both sides have the same registrable domain; ``0.0`` otherwise (including missing)."""
    obs_domain = registrable_domain(obs.domain) if obs.domain else None
    if obs_domain is None or cand_domain is None:
        return 0.0  # strong-key budget stays unearned without a confirmed domain
    return 1.0 if obs_domain == cand_domain else 0.0


def _registry_agreement(obs: Observation, cand_registry: Mapping[str, str]) -> float:
    """``1.0`` when any normalized ``(namespace, id)`` pair overlaps; ``0.0`` when none do."""
    obs_reg = dict(canonical_registry_id(ns, v) for ns, v in obs.registry_ids.items())
    obs_pairs = {(ns, v) for ns, v in obs_reg.items() if v}
    cand_pairs = {(ns, v) for ns, v in cand_registry.items()}
    return 1.0 if obs_pairs & cand_pairs else 0.0


# --- candidate record ------------------------------------------------------
class _CandidateRecord(BaseModel):
    """Slim **right-hand side** of probabilistic scoring — one live DB entity + query-time cosine.

    Built by :func:`_fetch_account_records` from ``account_entity`` (and its embedding join).
    Not :class:`~clue_research.core.AccountEntity` (no status/merge fields) and not a
    :class:`Candidate` (no score yet): it is the feature bundle :func:`_score` compares against an
    :class:`Observation` before producing the ranked :class:`Candidate` output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    canonical_name: str
    primary_domain: str | None
    aliases: tuple[str, ...]
    hq_geo: dict[str, JsonValue] | None
    registry_ids: dict[str, str]
    cosine: float | None


def _score(obs: Observation, record: _CandidateRecord, policy: ResolutionPolicy) -> Candidate:
    w = policy.weights
    features = {
        "name_cosine": max(0.0, record.cosine) if record.cosine is not None else 0.0,
        "name_token_jaccard": _name_jaccard(obs.name, record.aliases),
        "geo_agreement": _geo_agreement(obs.geo, record.hq_geo),
        "alias_overlap": _alias_overlap(obs.aliases, record.aliases),
        "domain_agreement": _domain_agreement(obs, record.primary_domain),
        "registry_agreement": _registry_agreement(obs, record.registry_ids),
    }
    score = (
        w.name_cosine * features["name_cosine"]
        + w.name_token_jaccard * features["name_token_jaccard"]
        + w.geo_agreement * features["geo_agreement"]
        + w.alias_overlap * features["alias_overlap"]
        + w.domain_agreement * features["domain_agreement"]
        + w.registry_agreement * features["registry_agreement"]
    )
    return Candidate(entity_id=record.entity_id, score=round(score, 6), features=features)


# --- deterministic stage (no model call) -----------------------------------
async def _deterministic_account(conn: AsyncConnection, obs: Observation) -> EntityId | None:
    domain = registrable_domain(obs.domain) if obs.domain else None
    if domain is not None:
        hit = (
            await conn.execute(
                text("SELECT id FROM account_entity WHERE primary_domain = :d LIMIT 1"),
                {"d": domain},
            )
        ).scalar()
        if hit is not None:
            return await surviving_id(conn, EntityId(hit), EntityType.ACCOUNT)
    for ns, value in obs.registry_ids.items():
        norm_ns, norm_value = canonical_registry_id(ns, value)
        if not norm_value:
            continue
        hit = (
            await conn.execute(
                text("SELECT id FROM account_entity WHERE registry_ids->>:ns = :v LIMIT 1"),
                {"ns": norm_ns, "v": norm_value},
            )
        ).scalar()
        if hit is not None:
            return await surviving_id(conn, EntityId(hit), EntityType.ACCOUNT)
    return None


async def _deterministic_contact(conn: AsyncConnection, obs: Observation) -> EntityId | None:
    for raw in (obs.linkedin_url, obs.verified_email):
        if not raw:
            continue
        strong = raw.strip().rstrip("/").lower()
        hit = (
            await conn.execute(
                text(
                    "SELECT id FROM contact_entity "
                    "WHERE linkedin_url = :s OR verified_email = :s LIMIT 1"
                ),
                {"s": strong},
            )
        ).scalar()
        if hit is not None:
            return await surviving_id(conn, EntityId(hit), EntityType.CONTACT)
    return None


# --- probabilistic stage (accounts: pgvector + trigram + alias blocking) ----
def _block_keys(obs: Observation) -> list[str]:
    keys = {name_key(obs.name)}
    keys.update(name_key(a) for a in obs.aliases)
    return [k for k in keys if k]


async def _candidate_ids_account(
    conn: AsyncConnection, obs: Observation, query_vec: str, policy: ResolutionPolicy
) -> list[EntityId]:
    """Bounded candidate set: pgvector ANN ∪ alias-array overlap ∪ trigram, deduped (live only)."""
    ids: list[EntityId] = []
    seen: set[EntityId] = set()

    def _add(rows: Sequence[UUID]) -> None:
        for value in rows:
            eid = EntityId(value)
            if eid not in seen:
                seen.add(eid)
                ids.append(eid)

    ann = (
        (
            await conn.execute(
                text(
                    "SELECT e.entity_id FROM account_entity_embedding e "
                    "JOIN account_entity a ON a.id = e.entity_id "
                    "WHERE a.status <> 'merged' "
                    "ORDER BY e.embedding <=> CAST(:q AS vector) LIMIT :k"
                ),
                {"q": query_vec, "k": policy.top_k},
            )
        )
        .scalars()
        .all()
    )
    _add(ann)

    keys = _block_keys(obs)
    if keys:
        alias_hits = (
            (
                await conn.execute(
                    text(
                        "SELECT id FROM account_entity "
                        "WHERE status <> 'merged' AND aliases && :keys LIMIT :k"
                    ).bindparams(bindparam("keys", type_=ARRAY(Text()))),
                    {"keys": keys, "k": policy.top_k},
                )
            )
            .scalars()
            .all()
        )
        _add(alias_hits)

    if obs.name.strip():
        trgm = (
            (
                await conn.execute(
                    text(
                        "SELECT id FROM account_entity "
                        "WHERE status <> 'merged' AND similarity(canonical_name, :n) >= :thr "
                        "ORDER BY similarity(canonical_name, :n) DESC LIMIT :k"
                    ),
                    {"n": obs.name, "thr": policy.trigram_threshold, "k": policy.top_k},
                )
            )
            .scalars()
            .all()
        )
        _add(trgm)

    return ids


async def _fetch_account_records(
    conn: AsyncConnection, ids: Sequence[EntityId], query_vec: str
) -> list[_CandidateRecord]:
    if not ids:
        return []
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT a.id, a.canonical_name, a.primary_domain, a.aliases, a.hq_geo, "
                    "a.registry_ids, "
                    "CASE WHEN e.embedding IS NULL THEN NULL "
                    "     ELSE 1 - (e.embedding <=> CAST(:q AS vector)) END AS cosine "
                    "FROM account_entity a "
                    "LEFT JOIN account_entity_embedding e ON e.entity_id = a.id "
                    "WHERE a.id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"q": query_vec, "ids": list(ids)},
            )
        )
        .mappings()
        .all()
    )
    records: list[_CandidateRecord] = []
    for row in rows:
        # model_validate coerces the decoded jsonb (dict / None) into the typed fields and
        # re-runs validation on read (defense in depth), with no manual casting.
        records.append(
            _CandidateRecord.model_validate(
                {
                    "entity_id": row["id"],
                    "canonical_name": row["canonical_name"],
                    "primary_domain": row["primary_domain"],
                    "aliases": tuple(row["aliases"] or ()),
                    "hq_geo": decode_jsonb(row["hq_geo"]),
                    "registry_ids": decode_jsonb(row["registry_ids"]) or {},
                    "cosine": float(row["cosine"]) if row["cosine"] is not None else None,
                }
            )
        )
    return records


async def _probabilistic_account(
    conn: AsyncConnection, obs: Observation, policy: ResolutionPolicy, embedder: Embedder
) -> ResolutionResult:
    query_vec = vector_literal(embedder.embed(obs.name))
    ids = await _candidate_ids_account(conn, obs, query_vec, policy)
    records = await _fetch_account_records(conn, ids, query_vec)
    scored = sorted((_score(obs, r, policy) for r in records), key=lambda c: c.score, reverse=True)[
        : policy.top_k
    ]
    return ResolutionResult(
        method=ResolutionMethod.PROBABILISTIC,
        candidates=tuple(scored),
        top_score=scored[0].score if scored else 0.0,
    )


# --- the seam --------------------------------------------------------------
async def resolve(
    conn: AsyncConnection,
    observation: Observation,
    *,
    policy: ResolutionPolicy = DEFAULT_RESOLUTION_POLICY,
    embedder: Embedder = DEFAULT_EMBEDDER,
) -> ResolutionResult:
    """Resolve one observation to ranked candidate ids (deterministic first, probabilistic second).

    A strong-key hit short-circuits at score ``1.0`` with **zero** embedding/scorer work. Only on a
    miss is the name embedded and the fuzzy candidate set scored. The result is *candidates*, not a
    decision — M2.3 disposes (auto-merge / review / new entity).
    """
    if observation.entity_type is EntityType.ACCOUNT:
        hit = await _deterministic_account(conn, observation)
        if hit is not None:
            return ResolutionResult(
                method=ResolutionMethod.DETERMINISTIC,
                candidates=(Candidate(entity_id=hit, score=1.0, features={"strong_key": 1.0}),),
                top_score=1.0,
            )
        return await _probabilistic_account(conn, observation, policy, embedder)

    if observation.entity_type is EntityType.CONTACT:
        hit = await _deterministic_contact(conn, observation)
        if hit is not None:
            return ResolutionResult(
                method=ResolutionMethod.DETERMINISTIC,
                candidates=(Candidate(entity_id=hit, score=1.0, features={"strong_key": 1.0}),),
                top_score=1.0,
            )
        # Contact fuzzy resolution (no embedding table) is deferred — committee contact matching
        # (modes M3/M4) lands with M8; M2.2 ships the deterministic contact path + account engine.
        return ResolutionResult(method=ResolutionMethod.PROBABILISTIC, candidates=(), top_score=0.0)

    return ResolutionResult(method=ResolutionMethod.NONE, candidates=(), top_score=0.0)


async def resolve_many(
    conn: AsyncConnection,
    observations: Sequence[Observation],
    *,
    policy: ResolutionPolicy = DEFAULT_RESOLUTION_POLICY,
    embedder: Embedder = DEFAULT_EMBEDDER,
) -> list[ResolutionResult]:
    """Bulk resolution (Scenario B): one :class:`ResolutionResult` per input row, never throwing on
    a garbage row (it surfaces as a ``NONE`` result). The caller (import) partitions by
    ``top_score`` into resolved / mid-band / unresolvable and handles each explicitly (Doc B §4)."""
    results: list[ResolutionResult] = []
    for obs in observations:
        # A per-row savepoint so a row that errors at the DB rolls back *itself* and the batch
        # continues — "never throws on garbage rows" holds even for a row that poisons its query.
        savepoint = await conn.begin_nested()
        try:
            result = await resolve(conn, obs, policy=policy, embedder=embedder)
            await savepoint.commit()
            results.append(result)
        except Exception:  # noqa: BLE001 — a bad row must not abort the batch (Doc B §4)
            await savepoint.rollback()
            results.append(
                ResolutionResult(method=ResolutionMethod.NONE, candidates=(), top_score=0.0)
            )
    return results
