"""M4.4 static invariants (DB-free) — the "nothing downstream knows the provider" guarantees,
made checkable: no provider leak, no resolver imports another, no secret in source/fixtures, and
registration binds every provider at tier 1. These run on every ``make check`` (no DB gate).
"""

from __future__ import annotations

import ast
from pathlib import Path

from clue_config import redact
from clue_research.resolvers import (
    apollo,
    builtwith,
    clay,
    get_json,  # noqa: F401 — imported to assert the shared HTTP wrapper exists (decision 3b)
    register_deterministic_resolvers,
    resolve_credential,  # noqa: F401 — the auth_ref→credential resolver exists (decision 3b)
    sumble,
    zoominfo,
)
from clue_research.resolvers.registries import SPECS
from clue_research.sources import get_resolver, is_resolver_bound

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src"
_RES_SRC = _SRC_ROOT / "clue_research" / "resolvers"
_RES_TESTS = _REPO_ROOT / "tests" / "resolvers"
_PROVIDER_PKGS = (
    "clay",
    "apollo",
    "zoominfo",
    "builtwith",
    "registries",
    "crm",
    "firecrawl",
    "sumble",
)
_REDACTED = "***REDACTED***"

# The only string literals that legitimately trip the runtime redactor (see the secret-scan test):
# the redaction sentinel itself, a request param NAME, and public symbol NAMES (long enough to look
# like an opaque token). None is a secret; every other redactor hit (a DSN-with-creds, a prefixed
# key, OR an opaque high-entropy token) is.
_ALLOWED_LITERALS = frozenset(
    {
        _REDACTED,
        "api_key",
        "register_deterministic_resolvers",
        "register_scrape_resolver",
        # M11 tier-4 synthesis public symbol names (≥24 chars → trip the opaque-token shape).
        "register_exa_deep_resolver",
        "register_synthesis_resolver",
        "GroundedSynthesisResolver",
        "register_parallel_task_resolver",
        "normalize_parallel_response",
    }
)


def _imported_modules(path: Path) -> set[str]:
    """Every module an import in ``path`` references (dotted), **including relative imports**, made
    absolute — so both ``from clue_research.resolvers import apollo`` and a relative
    ``from ..apollo import x`` / ``from . import apollo`` yield ``clue_research.resolvers.apollo``
    (a relative import is exactly how one provider could sneak an import of a sibling)."""
    anchor = (
        path.relative_to(_SRC_ROOT).with_suffix("").parts[:-1]
    )  # the package containing this file
    mods: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                package = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join((*package, node.module)) if node.module else ".".join(package)
            if base:
                mods.add(base)
                mods.update(f"{base}.{alias.name}" for alias in node.names)
    return mods


def _string_constants(path: Path) -> list[str]:
    return [
        node.value
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_resolvers_never_branch_on_provider_name() -> None:
    """No resolver module reads ``.provider`` — the 'nothing knows the provider' invariant
    (the column lives on the manifest, owned by sources/, never consumed by name here)."""
    offenders = [
        f"{path.relative_to(_RES_SRC)}:{lineno}"
        for path in _RES_SRC.rglob("*.py")
        for lineno, line in enumerate(path.read_text().splitlines(), 1)
        if ".provider" in line
    ]
    assert not offenders, f"resolvers must not branch on .provider: {offenders}"


def test_no_provider_subpackage_imports_another() -> None:
    """No resolver imports a *sibling provider* (conventions §2; the AC's static check). Shared
    modules (base/live/http) are fine — independence is between concrete providers."""
    offenders: list[str] = []
    for pkg in _PROVIDER_PKGS:
        forbidden = {f"clue_research.resolvers.{other}" for other in _PROVIDER_PKGS if other != pkg}
        for path in (_RES_SRC / pkg).rglob("*.py"):
            for mod in _imported_modules(path):
                if any(mod == f or mod.startswith(f + ".") for f in forbidden):
                    offenders.append(f"{path.relative_to(_RES_SRC)} imports {mod}")
    assert not offenders, f"a resolver imports another resolver: {offenders}"


def test_no_secret_shaped_strings_in_source_or_fixtures() -> None:
    """No secret-shaped string literal appears in resolver source *or* test fixtures — credentials
    are resolved via ``auth_ref`` at call time, never committed (the AC). Uses the SAME oracle the
    runtime redactor (``redact``) so the static scan and the redactor can never drift and the sound
    opaque-token shape is covered, minus a small allowlist of known-safe non-secret literals."""
    offenders: list[str] = []
    for root in (_RES_SRC, _RES_TESTS):
        for path in root.rglob("*.py"):
            offenders.extend(
                f"{path.name}: {value!r}"
                for value in _string_constants(path)
                if redact(value) == _REDACTED and value not in _ALLOWED_LITERALS
            )
    assert not offenders, f"secret-shaped literal in source/fixtures: {offenders}"


def test_auth_refs_are_clue_references_not_secrets() -> None:
    """Every resolver's declared ``auth_ref`` is a ``CLUE_*`` env-var *reference* (or ``None`` for a
    public registry), never a secret value."""
    refs = [
        clay.AUTH_REF,
        apollo.AUTH_REF,
        zoominfo.AUTH_REF,
        builtwith.AUTH_REF,
        sumble.AUTH_REF,
    ]
    refs += [spec.auth_ref for spec in SPECS.values() if spec.auth_ref is not None]
    for ref in refs:
        assert ref.startswith("CLUE_"), ref
        assert redact(ref) != _REDACTED, ref


def test_every_seeded_auth_ref_resolves_to_a_secrets_field() -> None:
    """Every credentialed source's ``auth_ref`` maps to a real ``Secrets`` field. ``Secrets`` uses
    ``extra="ignore"``, so a manifest ``auth_ref`` with no matching field would silently resolve to
    ``None`` even when the env var IS set (the DUNS gap) — making the source's live credential
    credential unresolvable. This guard fails the moment a credentialed source lacks its field."""
    from clue_config import Secrets
    from clue_research.sources import SEED_MANIFESTS

    for manifest in SEED_MANIFESTS:
        if manifest.auth_ref is not None:
            field = manifest.auth_ref.lower().removeprefix("clue_")
            assert field in Secrets.model_fields, (
                f"{manifest.source_key}: auth_ref {manifest.auth_ref} -> no Secrets field {field!r}"
            )


def test_crm_relationship_field_enum_matches_the_taxonomy() -> None:
    """The ``account.crm_relationship_status`` value-schema enum (registered in the core pack) stays
    in lock-step with the :class:`CrmRelationship` taxonomy the CRM resolver emits — so a value can
    never be produced that ``insert_claim``'s value-schema check would reject (drift guard)."""
    from clue_research.claimstore import CORE_PACK
    from clue_research.resolvers import CRM_RELATIONSHIP_FIELD, CrmRelationship

    seed = next(s for s in CORE_PACK if s.field_def.field_key == CRM_RELATIONSHIP_FIELD)
    assert seed.value_schema is not None
    assert set(seed.value_schema["enum"]) == {r.value for r in CrmRelationship}


def test_registration_binds_all_eight_resolvers_at_tier_1() -> None:
    """``register_deterministic_resolvers`` binds every provider to its ``source_key`` at tier 1
    (the cost comes from the in-memory seed manifests — no DB needed)."""
    register_deterministic_resolvers()
    for source_key in ("clay", "apollo", "zoominfo", "builtwith", "npi", "duns", "cik", "lei"):
        assert is_resolver_bound(source_key), source_key
        assert get_resolver(source_key).tier == 1
