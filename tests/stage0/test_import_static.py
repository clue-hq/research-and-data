"""Static (no-database) tests for M5.3 — run in the default ``make check``.

Exercises the import contracts, the reuse policy, the field set, the deterministic batch run id, and
the pure resolution/flag helpers without a connection.
"""

from __future__ import annotations

from clue_research.icp import TierBand, TierCutoffs
from clue_research.stage0 import (
    CONTACT_IMPORT_RECORD,
    IMPORT_BATCH,
    IMPORT_PACK,
    IMPORT_REUSE_POLICY,
    FitFlag,
    ImportContactRow,
    ImportResult,
    ImportRow,
    NeedsReviewRow,
    ResolvedAccount,
    UnresolvedRow,
    import_batch_run_id,
)
from clue_research.stage0.import_accounts import (
    _fit_flag,
    _has_identity,
    _identity_signal,
    _strong_key,
)


def test_import_reuse_policy_is_tenant_private_for_import_and_crm() -> None:
    assert "import." in IMPORT_REUSE_POLICY.tenant_private_prefixes
    # CRM-imported claims stay tenant-private by extraction method (inherited from the M2 default)
    assert "crm_import" in IMPORT_REUSE_POLICY.tenant_private_methods
    # the contact namespace is private too (so contact.import_record stamps tenant_private)
    assert "contact." in IMPORT_REUSE_POLICY.tenant_private_prefixes


def test_import_field_constants() -> None:
    assert IMPORT_BATCH == "import.batch"
    assert IMPORT_BATCH.startswith(f"{IMPORT_PACK}.")
    assert CONTACT_IMPORT_RECORD == "contact.import_record"


def test_import_batch_run_id_is_deterministic() -> None:
    assert import_batch_run_id("batch-1") == import_batch_run_id("batch-1")
    assert import_batch_run_id("batch-1") != import_batch_run_id("batch-2")


def test_fit_flag_uses_the_lowest_band_floor() -> None:
    cutoffs = TierCutoffs(bands=(TierBand(tier="high", min_fit=0.5),), fallback_tier="low")
    assert _fit_flag(0.6, cutoffs) is FitFlag.FIT
    assert _fit_flag(0.4, cutoffs) is FitFlag.NON_FIT
    # no fit floor configured → nothing is flagged (the client set no bar)
    assert _fit_flag(0.0, TierCutoffs()) is FitFlag.FIT


def test_strong_key_and_identity_signal() -> None:
    by_domain = ImportRow(row_index=1, name="Acme", domain="acme.com")
    assert _strong_key(by_domain) == "domain:acme.com"
    assert _identity_signal(_strong_key(by_domain)) == "domain"

    # the registry id is canonicalized exactly as the M2 DB paths do (DUNS upper, separators
    # stripped), so textual variants collapse to one key
    by_registry = ImportRow(row_index=2, name="Beta", registry_ids={"duns": "12-345"})
    assert _strong_key(by_registry) == "registry:DUNS:12345"
    assert (
        _strong_key(ImportRow(row_index=2, registry_ids={"DUNS": "123 45"}))
        == "registry:DUNS:12345"
    )
    assert _identity_signal(_strong_key(by_registry)) == "registry"

    name_only = ImportRow(row_index=3, name="Gamma")
    assert _strong_key(name_only) is None
    assert _identity_signal(_strong_key(name_only)) == "name+geo"

    empty = ImportRow(row_index=4)
    assert _strong_key(empty) is None
    assert not _has_identity(empty)
    assert _has_identity(by_domain)


def test_import_result_counts() -> None:
    result = ImportResult(
        import_batch_id="b",
        resolved=(
            _resolved(1, FitFlag.FIT),
            _resolved(2, FitFlag.NON_FIT),
        ),
        needs_review=(NeedsReviewRow(row_index=3, task_id=_eid(), top_score=0.8),),
        unresolved=(UnresolvedRow(row_index=4, reason="no identity"),),
    )
    assert result.row_count == 4
    assert result.non_fit_count == 1


def test_import_contact_row_defaults_to_professional_public() -> None:
    from clue_research.core import UseClass

    assert ImportContactRow(name="X").use_class is UseClass.PROFESSIONAL_PUBLIC


def _eid() -> object:
    from uuid import uuid4

    from clue_research.core import EntityId

    return EntityId(uuid4())


def _resolved(row_index: int, flag: FitFlag) -> ResolvedAccount:
    from clue_research.core import Score

    return ResolvedAccount(
        account_entity_id=_eid(),  # type: ignore[arg-type]
        row_index=row_index,
        fit_score=Score(value=1.0),
        intent_score=Score(value=0.0),
        fit_flag=flag,
        resolution_method="new_entity",
        matched_signal="new_entity",
        resolution_confidence=1.0,
    )
