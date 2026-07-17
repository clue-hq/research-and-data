"""M2.2 (ENG-106) — the resolution engine, against a live Postgres (pgvector + pg_trgm).

Covers every §M2.2 acceptance criterion: deterministic-first proven by a call-count assertion, the
Doc B IBM worked example, the never-silently-collapse rule, bounded top-K, bulk mode robustness,
config-swappability, and the embedding-dimension parity guard.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_core import EntityType
from clue_research.identity import (
    DEFAULT_EMBEDDER,
    DEFAULT_RESOLUTION_POLICY,
    EMBEDDING_DIM,
    HashingEmbedder,
    Observation,
    ResolutionMethod,
    ResolutionPolicy,
    ScorerWeights,
    embed_account,
    insert_account_entity,
    mark_merged,
    max_fuzzy_score,
    resolve,
    resolve_many,
)
from clue_research.identity.embedding import Embedder

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_identity_db")


class _SpyEmbedder:
    """Wraps the default embedder and counts ``embed`` calls (to prove the deterministic skip)."""

    def __init__(self) -> None:
        self._inner: Embedder = DEFAULT_EMBEDDER
        self.calls = 0

    @property
    def dimension(self) -> int:
        return self._inner.dimension

    @property
    def model_version(self) -> str:
        return self._inner.model_version

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return self._inner.embed(text)


async def _seed(conn: object, **kwargs: object) -> object:
    eid = await insert_account_entity(conn, **kwargs)  # type: ignore[arg-type]
    await embed_account(conn, eid)  # type: ignore[arg-type]
    return eid


def test_deterministic_domain_hit_makes_zero_model_calls() -> None:
    """An exact domain match resolves deterministically at 1.0 with ZERO embedding calls."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            acme = await _seed(conn, canonical_name="Acme", primary_domain="acme.com")
            spy = _SpyEmbedder()
            result = await resolve(
                conn, Observation(name="Acme Inc", domain="https://www.acme.com/"), embedder=spy
            )
            assert result.method is ResolutionMethod.DETERMINISTIC
            assert result.top_score == 1.0
            assert result.top is not None and result.top.entity_id == acme
            assert spy.calls == 0  # deterministic-first proven, not merely configured

    run_async(_run())


def test_deterministic_registry_hit() -> None:
    """An exact registry-id match resolves deterministically (normalized both sides)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            acme = await _seed(conn, canonical_name="Acme", registry_ids={"DUNS": "123456789"})
            spy = _SpyEmbedder()
            result = await resolve(
                conn,
                Observation(name="Acme", registry_ids={"duns": "12-345-6789"}),
                embedder=spy,
            )
            assert result.method is ResolutionMethod.DETERMINISTIC
            assert result.top is not None and result.top.entity_id == acme
            assert spy.calls == 0

    run_async(_run())


def test_ibm_variants_resolve_to_the_same_entity() -> None:
    """Doc B §4: every IBM surface form (and the domain) resolves to the same entity_id; a
    distractor (Globex) is never the top match, and an unknown/parked domain forces no collapse."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ibm = await _seed(
                conn,
                canonical_name="International Business Machines",
                primary_domain="ibm.com",
                aliases=["IBM", "I.B.M.", "International Business Machines Corp."],
            )
            await _seed(conn, canonical_name="Globex Pharmaceuticals", primary_domain="globex.com")

            for name in ("IBM", "I.B.M.", "International Business Machines Corp."):
                result = await resolve(conn, Observation(name=name))
                assert result.top is not None, f"no candidate for {name!r}"
                assert result.top.entity_id == ibm, f"{name!r} did not resolve to IBM"

            # The real domain resolves deterministically.
            by_domain = await resolve(conn, Observation(name="IBM", domain="ibm.com"))
            assert by_domain.method is ResolutionMethod.DETERMINISTIC
            assert by_domain.top is not None and by_domain.top.entity_id == ibm

            # An unknown/parked domain is NOT trusted: it misses deterministically and the name
            # (Globex) drives a probabilistic resolution — no wrong collapse onto IBM.
            parked = await resolve(
                conn, Observation(name="Globex", domain="ibm-parked-stale.example")
            )
            assert parked.method is ResolutionMethod.PROBABILISTIC
            assert parked.top is not None and parked.top.entity_id != ibm

    run_async(_run())


def test_same_name_different_geo_do_not_collapse() -> None:
    """Two genuinely distinct same-name companies in different geos surface as separate candidates
    with sub-auto-merge scores (substrate §2 — never silently collapse two real companies)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            us = await _seed(
                conn,
                canonical_name="Apex Logistics",
                primary_domain="apexlogistics.com",
                hq_geo={"country": "US"},
            )
            de = await _seed(
                conn,
                canonical_name="Apex Logistics",
                primary_domain="apex-logistics.de",
                hq_geo={"country": "DE"},
            )
            result = await resolve(conn, Observation(name="Apex Logistics", geo={"country": "US"}))
            ids = {c.entity_id for c in result.candidates}
            assert {us, de} <= ids  # both surfaced, neither collapsed away
            # No strong key → the top score is structurally capped below the auto-merge band, at the
            # scorer's strong-key-free ceiling (not just "< 0.95", which any fuzzy match satisfies).
            assert result.top_score <= max_fuzzy_score(DEFAULT_RESOLUTION_POLICY)
            assert max_fuzzy_score(DEFAULT_RESOLUTION_POLICY) < 0.95
            assert result.top is not None and result.top.entity_id == us  # geo breaks the tie

    run_async(_run())


def test_bulk_resolve_many_partitions_without_throwing() -> None:
    """Bulk mode returns one result per row and never throws on a garbage row."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            acme = await _seed(conn, canonical_name="Acme", primary_domain="acme.com")
            rows = [
                Observation(name="Acme", domain="acme.com"),  # deterministic
                Observation(name="Totally Unknown Co"),  # probabilistic, no match
                Observation(name=""),  # garbage: empty name
                Observation(name="🙂🙂🙂 \x00 weird"),  # garbage: junk
            ]
            results = await resolve_many(conn, rows)
            assert len(results) == len(rows)
            assert results[0].method is ResolutionMethod.DETERMINISTIC
            assert results[0].top is not None and results[0].top.entity_id == acme
            # The unknown / garbage rows resolved to nothing meaningful but did not raise.
            assert results[1].top_score < 0.95
            assert results[2].method in (ResolutionMethod.PROBABILISTIC, ResolutionMethod.NONE)

    run_async(_run())


def test_candidate_set_is_bounded_top_k() -> None:
    """Candidate generation returns at most ``top_k`` candidates even with many near-matches."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            for i in range(15):
                await _seed(conn, canonical_name=f"Apex Logistics {i}")
            policy = ResolutionPolicy(top_k=10)
            result = await resolve(conn, Observation(name="Apex Logistics"), policy=policy)
            assert len(result.candidates) <= 10

    run_async(_run())


def test_swapping_policy_changes_scores_without_code_change() -> None:
    """Swapping the policy version/weights changes the score with no code edit (policy is data)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await _seed(conn, canonical_name="Apex Logistics", hq_geo={"country": "US"})
            obs = Observation(name="Apex Logistics", geo={"country": "US"})
            default = await resolve(conn, obs)
            tuned = await resolve(
                conn,
                obs,
                policy=ResolutionPolicy(
                    version=2,
                    weights=ScorerWeights(
                        name_cosine=0.6,
                        name_token_jaccard=0.1,
                        geo_agreement=0.1,
                        alias_overlap=0.05,
                        domain_agreement=0.1,
                        registry_agreement=0.05,
                    ),
                ),
            )
            assert default.top_score != tuned.top_score

    run_async(_run())


def test_swapping_embedder_model_version_re_embeds() -> None:
    """Re-embedding under a new model_version replaces the row; ``resolve``'s signature is same."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ibm = await insert_account_entity(
                conn, canonical_name="International Business Machines"
            )
            v2 = HashingEmbedder(model_version="hash-trigram-v2")
            await embed_account(conn, ibm, embedder=v2)
            stored = (
                await conn.execute(
                    text("SELECT model_version FROM account_entity_embedding WHERE entity_id = :e"),
                    {"e": ibm},
                )
            ).scalar()
            assert stored == "hash-trigram-v2"
            result = await resolve(
                conn, Observation(name="International Business Machines"), embedder=v2
            )
            assert result.top is not None and result.top.entity_id == ibm

    run_async(_run())


def test_resolve_follows_merge_to_survivor() -> None:
    """A deterministic hit on a merged loser resolves through to the survivor."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            survivor = await _seed(conn, canonical_name="Acme", primary_domain="acme.com")
            loser = await _seed(conn, canonical_name="Old Acme", primary_domain="old-acme.com")
            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)
            result = await resolve(conn, Observation(name="x", domain="old-acme.com"))
            assert result.method is ResolutionMethod.DETERMINISTIC
            assert result.top is not None and result.top.entity_id == survivor

    run_async(_run())


def test_embedding_dimension_parity() -> None:
    """The DB ``vector(N)`` column dimension equals the Python EMBEDDING_DIM constant (drift)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            declared = (
                await conn.execute(
                    text(
                        "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                        "WHERE a.attrelid = 'account_entity_embedding'::regclass "
                        "AND a.attname = 'embedding'"
                    )
                )
            ).scalar()
            assert declared == f"vector({EMBEDDING_DIM})"

    run_async(_run())
