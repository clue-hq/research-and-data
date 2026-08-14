"""C9's executable §20 manifest and cross-slice pure adversarial guards."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from uuid import uuid4

from clue_research.official_site import (
    EXTRACTION_PROMPT_VERSION,
    EXTRACTION_SCHEMA_VERSION,
    Corpus,
    CorpusPage,
    CrawlPhase,
    ExtractionCategory,
    GroundedOfficialSiteMaterializer,
    OfficialSiteMaterializationRequest,
    PageCategory,
)

_REPO = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO / "tests/fixtures/official_site/c9_acceptance_matrix.json"
_SECTION_COUNTS = {
    "20.1": 6,
    "20.2": 7,
    "20.3": 8,
    "20.4": 5,
    "20.5": 7,
    "20.6": 6,
    "20.7": 8,
    "20.8": 6,
}
_CRASH_BOUNDARIES = {
    "prepared_before_dispatch",
    "dispatched_with_lookup",
    "dispatched_without_lookup",
    "provider_success_result_retained",
    "provider_success_result_retrievable",
    "provider_success_result_unrecoverable",
    "persisted_before_page_completion",
    "retryable_no_spend",
    "terminal_policy_or_robots",
}


def _assert_executable_nodeids(entries: list[dict[str, object]]) -> None:
    parsed: dict[Path, set[str]] = {}
    for entry in entries:
        nodeids = entry["nodeids"]
        assert isinstance(nodeids, list) and nodeids, entry
        for nodeid in nodeids:
            assert isinstance(nodeid, str) and nodeid.count("::") == 1, entry
            relative, function_name = nodeid.split("::", maxsplit=1)
            path = _REPO / relative
            assert path.is_file(), entry
            if path not in parsed:
                module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                parsed[path] = {
                    node.name
                    for node in module.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
            assert function_name in parsed[path], entry


def test_c9_manifest_covers_every_section_20_row_and_crash_boundary() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert payload["spec"] == "FI durable official-site crawl C9 section 20"
    assert payload["provider_mode"] == "offline-fakes-only"
    cases = payload["cases"]
    assert isinstance(cases, list)
    assert payload["case_count"] == len(cases) == sum(_SECTION_COUNTS.values()) == 53
    case_ids = [entry["id"] for entry in cases]
    assert len(case_ids) == len(set(case_ids))
    for section, expected in _SECTION_COUNTS.items():
        assert sum(str(case_id).startswith(f"{section}.") for case_id in case_ids) == expected
    _assert_executable_nodeids(cases)

    crashes = payload["crash_boundaries"]
    assert isinstance(crashes, list)
    assert {entry["id"] for entry in crashes} == _CRASH_BOUNDARIES
    _assert_executable_nodeids(crashes)


def test_missing_category_builds_empty_operations_without_model_work() -> None:
    snapshot = CorpusPage(
        snapshot_id=uuid4(),
        fetch_attempt_id=uuid4(),
        final_url="https://example.com/product",
        artifact_key="workspace/" + "a" * 64,
        content_sha256="a" * 64,
        media_type="text/plain",
        category=PageCategory.PRODUCT,
        normalized_text="Product evidence only.",
    )
    corpus = Corpus(
        workspace_id="workspace",
        crawl_run_id=uuid4(),
        checkpoint_id=uuid4(),
        pages=(snapshot,),
    )
    request = OfficialSiteMaterializationRequest(
        workspace_id="workspace",
        crawl_run_id=corpus.crawl_run_id,
        recon_run_id=uuid4(),
        claim_run_id=uuid4(),
        client_entity_id=uuid4(),
        checkpoint_id=corpus.checkpoint_id,
        phase=CrawlPhase.FAST,
        model_id="openai/gpt-5.6-luna",
        prompt_version=EXTRACTION_PROMPT_VERSION,
        schema_version=EXTRACTION_SCHEMA_VERSION,
    )
    materializer = GroundedOfficialSiteMaterializer(
        gateway=object(),  # type: ignore[arg-type]
        storage=object(),  # type: ignore[arg-type]
    )
    operations = materializer._operations(request, corpus)
    assert len(operations) == 11
    company = tuple(
        operation
        for operation in operations
        if operation.category is ExtractionCategory.COMPANY_CONTEXT
    )
    assert company
    assert all(operation.pages == () for operation in company)
    product = tuple(
        operation
        for operation in operations
        if operation.category is ExtractionCategory.PRODUCT_VALUE
    )
    assert product and all(operation.pages == (snapshot,) for operation in product)
