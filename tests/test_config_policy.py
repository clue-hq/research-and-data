"""M0.4 — per-client jurisdiction/policy skeleton tests (ENG-120).

Covers the policy acceptance criteria of docs/specs/M00 §M0.4:
* default policy = Option 1 / GDPR-grade / full source-scope / ``sensitive`` not usable;
* setting Option 3 (config-only, no code change) flips source-scope to professional-public-only;
* the allow-map enforces "sensitive may not be USABLE in the skeleton" (Doc D §4).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_config import (
    DEFAULT_JURISDICTION,
    DEFAULT_POSTURE,
    Jurisdiction,
    JurisdictionPolicy,
    Posture,
    SourceScope,
    UseDisposition,
    get_policy,
)
from clue_core import UseClass


def test_default_policy_is_option1_gdpr_fullsweep_sensitive_locked() -> None:
    """A client with no overrides → Option 1, GDPR-grade, full sweep, sensitive not usable."""
    policy = get_policy("client-with-no-overrides")

    assert policy.posture is Posture.CONSERVATIVE_DEFAULT  # Option 1
    assert policy.posture is DEFAULT_POSTURE
    assert policy.jurisdiction is Jurisdiction.GDPR  # GDPR-grade strict default
    assert policy.jurisdiction is DEFAULT_JURISDICTION
    assert policy.source_scope is SourceScope.FULL_SWEEP

    # professional-public + personal-public-non-sensitive are usable for outreach.
    assert policy.disposition_for(UseClass.PROFESSIONAL_PUBLIC) is UseDisposition.USABLE
    assert policy.disposition_for(UseClass.PERSONAL_PUBLIC_NON_SENSITIVE) is UseDisposition.USABLE
    # sensitive (special-category) is NOT usable for outreach (Doc D §6 Option 1).
    assert policy.disposition_for(UseClass.SENSITIVE) is not UseDisposition.USABLE
    assert policy.disposition_for(UseClass.SENSITIVE) is UseDisposition.STORED_UNUSABLE


def test_option3_flips_source_scope_to_professional_public_only() -> None:
    """Posture = Option 3 via config (no code change) scopes research at the source level to
    professional-public-only, so the deep personal-life classes are never collected (Doc D §6)."""
    # Config-only change: set only the posture field; the source-scope is derived, not set.
    option3 = JurisdictionPolicy(posture=Posture.PROFESSIONAL_PUBLIC_ONLY)

    assert option3.source_scope is SourceScope.PROFESSIONAL_PUBLIC_ONLY
    # Other postures keep the full sweep.
    assert JurisdictionPolicy(posture=Posture.CONSERVATIVE_DEFAULT).source_scope is (
        SourceScope.FULL_SWEEP
    )
    assert JurisdictionPolicy(posture=Posture.GATHER_BROADLY_GATE_AT_USE).source_scope is (
        SourceScope.FULL_SWEEP
    )


def test_allow_map_rejects_sensitive_usable() -> None:
    """The skeleton forbids marking sensitive special-category data USABLE (Doc D §4)."""
    with pytest.raises(ValidationError):
        JurisdictionPolicy(
            allow_map={
                UseClass.PROFESSIONAL_PUBLIC: UseDisposition.USABLE,
                UseClass.PERSONAL_PUBLIC_NON_SENSITIVE: UseDisposition.USABLE,
                UseClass.SENSITIVE: UseDisposition.USABLE,  # not allowed
            }
        )


def test_allow_map_must_cover_every_use_class() -> None:
    """An incomplete allow-map fails on construction (every use-class needs a disposition)."""
    with pytest.raises(ValidationError):
        JurisdictionPolicy(
            allow_map={UseClass.PROFESSIONAL_PUBLIC: UseDisposition.USABLE},
        )


def test_sensitive_may_be_not_stored() -> None:
    """A regulated client may dial sensitive down to NOT_STORED (stronger than the default lock)."""
    policy = JurisdictionPolicy(
        allow_map={
            UseClass.PROFESSIONAL_PUBLIC: UseDisposition.USABLE,
            UseClass.PERSONAL_PUBLIC_NON_SENSITIVE: UseDisposition.STORED_UNUSABLE,
            UseClass.SENSITIVE: UseDisposition.NOT_STORED,
        }
    )
    assert policy.disposition_for(UseClass.SENSITIVE) is UseDisposition.NOT_STORED


def test_policy_is_frozen() -> None:
    """Policy objects are immutable (a config change is a new versioned object, not a mutation)."""
    policy = JurisdictionPolicy()
    with pytest.raises(ValidationError):
        policy.posture = Posture.PROFESSIONAL_PUBLIC_ONLY  # type: ignore[misc]
