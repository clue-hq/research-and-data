"""M10.4 (the three postures as per-client config) — one test per §M10.4 acceptance criterion.

Postures are presets over the same ``use_class × jurisdiction`` machinery (Doc D §6), so these are
pure (no-DB) tests of the materialization + the gather/store/use semantics. The DB-backed override
and the ``load_workspace_policy`` column round-trip live in ``test_use_gate.py``.
"""

from __future__ import annotations

from pathlib import Path

from clue_config import Jurisdiction, Posture, SourceScope, UseDisposition
from clue_core import UseClass, UseReason
from clue_research.compliance import (
    DEFAULT_POSTURE_POLICY,
    DEFAULT_WORKSPACE_POLICY,
    POSTURE_PRESETS,
    WorkspacePolicy,
    decide_use,
    workspace_policy_for_posture,
)

_PRO = UseClass.PROFESSIONAL_PUBLIC
_PERSONAL = UseClass.PERSONAL_PUBLIC_NON_SENSITIVE
_SENSITIVE = UseClass.SENSITIVE


def test_no_posture_resolves_to_option1() -> None:  # AC: a client with no posture → Option 1
    # the platform default (no posture set) is Option 1, materialized — and equals the bare default.
    assert DEFAULT_POSTURE_POLICY == DEFAULT_WORKSPACE_POLICY
    p = workspace_policy_for_posture(Posture.CONSERVATIVE_DEFAULT)
    assert p.posture is Posture.CONSERVATIVE_DEFAULT
    assert p.source_scope is SourceScope.FULL_SWEEP
    assert p.store_sensitive is False  # minimize (Doc D §4)
    # the gate (default policy) allows professional-public + personal-public and locks sensitive
    assert decide_use(_PRO, Jurisdiction.GDPR, p) == (True, UseReason.ALLOWED)
    assert decide_use(_PERSONAL, Jurisdiction.GDPR, p) == (True, UseReason.ALLOWED)
    assert decide_use(_SENSITIVE, Jurisdiction.GDPR, p) == (False, UseReason.SENSITIVE_LOCKED)


def test_option2_stores_sensitive_but_gate_still_locks_use() -> None:  # AC: Option 2
    p = workspace_policy_for_posture(Posture.GATHER_BROADLY_GATE_AT_USE)
    assert p.source_scope is SourceScope.FULL_SWEEP
    # gather broadly: sensitive IS stored...
    assert p.store_sensitive is True
    assert p.should_store(_SENSITIVE) is True
    # ...but the gate still locks its USE (the M10.3 hard floor — not config-bypassable)
    assert decide_use(_SENSITIVE, Jurisdiction.US_STATE, p) == (False, UseReason.SENSITIVE_LOCKED)


def test_option3_source_scoped_and_minimizes() -> None:  # AC: Option 3
    p = workspace_policy_for_posture(Posture.PROFESSIONAL_PUBLIC_ONLY)
    # research scoped at the source level → the deep personal-life dimension is never collected
    assert p.source_scope is SourceScope.PROFESSIONAL_PUBLIC_ONLY
    assert p.store_sensitive is False
    assert p.should_store(_SENSITIVE) is False
    # the use-gate is light: everything gathered is professional-public, which is usable
    assert decide_use(_PRO, Jurisdiction.GDPR, p) == (True, UseReason.ALLOWED)


def test_option1_store_sensitive_subflag_prevents_persistence() -> None:
    # AC: store_sensitive=false. Option 1 minimizes by default → sensitive claims are never
    # persisted at all (should_store False).
    p = workspace_policy_for_posture(Posture.CONSERVATIVE_DEFAULT)
    assert p.should_store(_SENSITIVE) is False
    # non-sensitive personal data is always storable (the gate governs its use, not storage)
    assert p.should_store(_PRO) is True
    assert p.should_store(_PERSONAL) is True


def test_per_jurisdiction_relaxation_reads_down_from_strict() -> None:  # AC: per-jurisdiction
    # the same posture yields stricter usability for GDPR than US_STATE where configured — a
    # regime-keyed lookup (design strict, switch down), not a branch.
    p = WorkspacePolicy(
        regime_overrides={Jurisdiction.GDPR: {_PERSONAL: UseDisposition.STORED_UNUSABLE}}
    )
    assert decide_use(_PERSONAL, Jurisdiction.GDPR, p) == (
        False,
        UseReason.USE_CLASS_DISALLOWED_FOR_REGIME,
    )
    assert decide_use(_PERSONAL, Jurisdiction.US_STATE, p) == (True, UseReason.ALLOWED)
    assert p.usable_use_classes(Jurisdiction.GDPR) == frozenset({_PRO})
    assert p.usable_use_classes(Jurisdiction.US_STATE) == frozenset({_PRO, _PERSONAL})


def test_postures_share_one_use_side_machinery() -> None:  # Doc D §6 — "not forks"
    # all three postures carry the SAME conservative use-side allow-map (sensitive locked); they
    # differ only on the gather/store-side. So usability is one machinery, the posture a setting.
    maps = {
        posture: tuple(sorted(workspace_policy_for_posture(posture).allow_map.items()))
        for posture in Posture
    }
    assert len(set(maps.values())) == 1  # identical allow-map across all postures
    for posture in Posture:
        pol = workspace_policy_for_posture(posture)
        assert pol.allow_map[_SENSITIVE] is UseDisposition.STORED_UNUSABLE


def test_three_postures_are_distinct_on_gather_store_side() -> None:
    presets = {posture: POSTURE_PRESETS[posture] for posture in Posture}
    # exactly the three postures are presets; each is distinct on (source_scope, store_sensitive)
    assert set(presets) == set(Posture)
    signatures = {(p.source_scope, p.store_sensitive) for p in presets.values()}
    assert len(signatures) == 3


def test_posture_change_bumps_policy_version() -> None:  # AC: a posture change bumps policy_version
    v1 = workspace_policy_for_posture(Posture.CONSERVATIVE_DEFAULT, version=1)
    v2 = workspace_policy_for_posture(Posture.GATHER_BROADLY_GATE_AT_USE, version=2)
    assert v1.version == 1
    assert v2.version == 2  # a subsequent gate decision records the new version


def test_m104_migration_defaults_match_code() -> None:
    # Pure no-DB drift guard (mirrors the M10.3 allow_map guard + the M9.4 binding_policy guard):
    # the migration's hand-written SQL DEFAULTs must equal the Option-1 / DEFAULT_WORKSPACE_POLICY
    # values, so a preset retune that forgets the migration (or vice-versa) fails `make check`
    # loudly without a database.
    import re

    src = (
        Path(__file__).resolve().parents[2]
        # the historical (pre-A3-rename) migration file — history is never rewritten, so the
        # filename keeps the old table name.
        / "alembic/versions/196d37e4a179_m10_4_posture_client_policy_columns.py"
    ).read_text()
    p = DEFAULT_WORKSPACE_POLICY  # == workspace_policy_for_posture(DEFAULT_POSTURE)

    ss = re.search(r"source_scope text NOT NULL DEFAULT '([^']*)'", src)
    assert ss is not None and ss.group(1) == p.source_scope.value  # 'full_sweep'
    st = re.search(r"store_sensitive boolean NOT NULL DEFAULT (true|false)", src)
    assert st is not None and (st.group(1) == "true") is p.store_sensitive  # false (Doc D §4)
    gs = re.search(r"gather_scope jsonb NOT NULL DEFAULT '(\[\])'", src)
    assert gs is not None and not p.gather_scope
    so = re.search(r"sensitive_overrides jsonb NOT NULL DEFAULT '(\[\])'", src)
    assert so is not None and not p.sensitive_overrides


def test_no_posture_named_branch_in_gate_or_collection() -> None:  # AC: "not permanent forks"
    # grep guard (Doc D §6): no posture-named if/elif branch exists in the gate or the posture
    # resolution — postures are DATA (the POSTURE_PRESETS table), never if/else. The preset dict
    # literal keys (``Posture.X: ...``) and field annotations are not conditionals and are allowed.
    here = Path(__file__).resolve().parents[2] / "src/clue_research/compliance"
    for module in ("use_gate.py", "posture.py"):
        for raw in (here / module).read_text().splitlines():
            line = raw.strip()
            assert not (line.startswith(("if ", "elif ")) and "Posture." in line), (
                f"{module}: posture-named branch is forbidden — {line!r}"
            )
            assert "is Posture." not in line and "== Posture." not in line, (
                f"{module}: posture-named comparison is forbidden — {line!r}"
            )
