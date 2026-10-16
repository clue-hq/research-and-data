"""Global Constraint 7, machine-checked: ``clue_api.arv2`` imports nothing quarantined.

The ARV2 lane is being built beside a large body of superseded research machinery (the M8D R1
quarantine, the old orchestrators, the Sumble lineage). A single convenience import from one of
those trees would silently re-couple the new lane to the code it exists to replace, and no other
gate would notice — so this one walks the package's own syntax tree.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ARV2 = REPO / "platform" / "api" / "clue_api" / "arv2"
ARV2_PACKAGE = "clue_api.arv2"

#: The only internal prefixes an ARV2 module may import. Everything else under ``clue_research``,
#: all of ``clue_memory``, and every ``clue_api`` module outside ``arv2`` are forbidden.
ALLOWED_INTERNAL_PREFIXES: tuple[str, ...] = (
    "clue_api.arv2",
    "clue_core",
    "clue_config",
    "clue_obs",
    "clue_storage",
    # lane 3 slice 5: the provider-caller seam itself — ARV2's calls/sinks/transport/errors and the
    # drain are re-export shims over it now, so every lane module reaches it by this name.
    "clue_spend",
    "clue_db",
    "clue_gateway",
    "clue_locks",
    "clue_spine",
    "clue_toolbelt",
    "clue_fleet",
    "clue_agents",
    "clue_execution",
    "clue_auth",
    "clue_projections",
    "clue_research.claimstore",
    # Quality design Q6: shared narrative field/support storage and use-policy helpers only.
    # This does not admit the legacy positioner, assembler, graph, or research orchestration.
    "clue_research.narrative.fields",
    "clue_research.narrative.support",
    "clue_research.compliance",
    # D1: the entity, membership and project-run writers the master plan keeps (not quarantined).
    "clue_research.identity",
    # Media v3 reuses these pure public-URL/DNS safety primitives. This does not admit the
    # official-site acquisition engine, agents, resolvers, scoring or source waterfall.
    "clue_research.official_site.safety",
    "clue_research.official_site.url_policy",
    "clue_research.membership",
    "clue_research.durable.project_run",
    # D1: the pack-loader list (composition root data, not a lane)
    "clue_api.composition",
    # D1: the wiring hook that appends the ARV2 pack (outside the lane by design)
    "clue_api.arv2_wiring",
    # PI-2: platform incident recorder the lane reports into; no lane logic
    "clue_api.provider_incidents",
    # Shared observability callback and document-change notification seams (no research owner).
    "clue_api.langfuse_callbacks",
    "clue_api.project_library_refresh",
    # The lane's own governed research-artifact sink (it imports clue_api.arv2 and sits on the
    # platform's durable agent artifact store) — dossiers, briefs, model inputs/outputs since
    # 2026-09-24. No research orchestration behind it.
    "clue_api.quality_research_artifacts",
    # Platform execution journal + run-event writer (C5.1 composition over clue_execution, which is
    # already allowed); account reconciliation emits its run events through it since 2026-09-28.
    "clue_api.execution_wiring",
    # The verified, content-addressed read of a knowledge file's bytes (a platform storage seam,
    # no research owner); project documents read a decision's source file through it.
    "clue_api.knowledge_bytes",
    # The display pages' readers (ARV2's account and contact pages); the read tools list an
    # account's buying committee exactly as the account screen does, reading only.
    "clue_api.frontend_read.display_pages",
)

#: Provider SDKs. Every ARV2 provider call goes over plain HTTP through the wrapper instead.
FORBIDDEN_SDK_ROOTS: frozenset[str] = frozenset(
    {"openai", "google", "exa_py", "firecrawl", "sumble"}
)

_INTERNAL_ROOT_PREFIX = "clue_"


def _resolve(module: str | None, level: int, package: str) -> str:
    """Resolve a possibly-relative import to its absolute dotted name."""
    if level == 0:
        return module or ""
    parts = package.split(".")
    base = parts[: len(parts) - (level - 1)] if level > 1 else parts
    return ".".join([*base, module]) if module else ".".join(base)


def _is_allowed(dotted: str) -> bool:
    root = dotted.split(".", 1)[0]
    if root in FORBIDDEN_SDK_ROOTS:
        return False
    if not root.startswith(_INTERNAL_ROOT_PREFIX):
        return True
    return any(
        dotted == prefix or dotted.startswith(prefix + ".") for prefix in ALLOWED_INTERNAL_PREFIXES
    )


def offending_imports(source: str, *, package: str) -> list[str]:
    """Every dotted import in ``source`` that Global Constraint 7 forbids."""
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            offenders.extend(alias.name for alias in node.names if not _is_allowed(alias.name))
        elif isinstance(node, ast.ImportFrom):
            dotted = _resolve(node.module, node.level, package)
            if dotted and not _is_allowed(dotted):
                offenders.append(dotted)
    return offenders


def _package_for(path: Path) -> str:
    relative = path.relative_to(ARV2).parts
    return ".".join([ARV2_PACKAGE, *relative[:-1]])


def test_the_arv2_package_imports_nothing_quarantined() -> None:
    modules = sorted(ARV2.rglob("*.py"))
    assert modules, f"no ARV2 modules found under {ARV2} — the guard would pass vacuously"

    offenders: list[str] = []
    for path in modules:
        for dotted in offending_imports(
            path.read_text(encoding="utf-8"), package=_package_for(path)
        ):
            offenders.append(f"{path.relative_to(REPO)}: {dotted}")
    assert not offenders, (
        "Global Constraint 7 — clue_api.arv2 may import only "
        f"{list(ALLOWED_INTERNAL_PREFIXES)} and no provider SDK; found: {offenders}"
    )


def test_the_guard_reports_a_quarantined_import_when_there_is_one() -> None:
    """The checker's own red case: a green guard must be proof, not an empty walk."""
    source = (
        "from clue_api.sumble_claim_materialization import materialize\n"
        "from clue_research.sources.waterfall import run\n"
        "from clue_research.narrative.positioner import position\n"
        "from clue_research.claimstore import insert_claim\n"
        "import httpx\n"
        "from clue_core.primitives import CostCents\n"
        "from .transport import HttpRequest\n"
    )
    assert offending_imports(source, package=ARV2_PACKAGE) == [
        "clue_api.sumble_claim_materialization",
        "clue_research.sources.waterfall",
        "clue_research.narrative.positioner",
    ]


def test_the_guard_reports_a_provider_sdk_import() -> None:
    source = "import openai\nfrom google.generativeai import configure\nimport exa_py\n"
    assert offending_imports(source, package=ARV2_PACKAGE) == [
        "openai",
        "google.generativeai",
        "exa_py",
    ]


# -- the uniform cost provision -----------------------------------------------------------------


def test_every_client_return_type_carries_the_cost_of_the_request_behind_it() -> None:
    """Cost tracking is a lane-wide provision, not a per-client courtesy.

    Every value an ARV2 client method hands back exists because a request was made, and every one
    of them carries that request's :class:`~clue_api.arv2.calls.CallCost` — so no caller ever has
    to ask "does this one report its cost?", and no future client can quietly opt out.

    A ``| None`` on the field is allowed and means one specific thing: the value can also be built
    **without a call** (a pure mapper or parser, a caller-supplied fetcher, or an operation that
    short-circuits before sending). Those cases are named in the package README; ``None`` is the
    honest answer there, because there is no ledger row to point at.
    """
    from dataclasses import fields

    from clue_api.arv2 import gemini_media_client, media_feeds_client
    from clue_api.arv2.ai_ark_client import AiArkCompany, AiArkEmailExport, AiArkPeople
    from clue_api.arv2.ats_client import BoardPostings
    from clue_api.arv2.exa_client import (
        ExaAgentRun,
        ExaContentsResult,
        ExaDeepResult,
        ExaSearchResult,
    )
    from clue_api.arv2.onboarding_documents import KnowledgeDocument
    from clue_api.arv2.structuring_client import StructuredOutput

    return_types = (
        AiArkCompany,
        AiArkEmailExport,
        AiArkPeople,
        BoardPostings,
        ExaSearchResult,
        ExaContentsResult,
        ExaDeepResult,
        ExaAgentRun,
        media_feeds_client.Podcast,
        media_feeds_client.AudioFile,
        gemini_media_client.Transcript,
        gemini_media_client.MinedQuotes,
        gemini_media_client.EmbeddedTranscript,
        StructuredOutput,
        KnowledgeDocument,
    )

    missing = [
        result_type.__name__
        for result_type in return_types
        if "cost" not in {f.name for f in fields(result_type)}
    ]
    assert missing == [], f"client return types with no cost field: {missing}"
