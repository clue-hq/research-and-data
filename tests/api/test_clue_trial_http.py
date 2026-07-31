"""HTTP contract tests for the local-only Clue Trial router."""

from __future__ import annotations

import ast
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clue_api.trial.coordinator import (
    AccountInput,
    ClueTrialCoordinator,
    ClueTrialManifest,
    CreateTrialInput,
    ResearchInput,
    TrialReadinessOverrideRequired,
    TurnInput,
)
from clue_api.trial_app import create_trial_router
from clue_api.trial_main import build_application
from clue_config import Settings

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

# The single definition of the HTTP-only ban for the trial CLI closure (see
# ``test_cli_source_is_http_only``). The trial CLI must reach the backend over HTTP only, so it may
# not import any package that owns durable state or domain logic.
_BANNED_DOMAIN_PACKAGES = (
    "clue_research",
    "clue_execution",
    "clue_fleet",
    "clue_memory",
    "clue_db",
    "clue_api",
)


def _script_local_imports(source: str) -> set[str]:
    """Top-level import names in ``source`` that resolve to another module in ``scripts/``."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    return {name for name in imported if (_SCRIPTS / f"{name}.py").is_file()}


def _http_only_closure(entry: str) -> list[Path]:
    """``entry`` plus every ``scripts/``-local module transitively reachable from it."""
    pending, seen, closure = [entry], set[str](), list[Path]()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        path = _SCRIPTS / f"{name}.py"
        closure.append(path)
        pending.extend(_script_local_imports(path.read_text(encoding="utf-8")))
    return closure


class _Coordinator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.raise_readiness = False

    async def execute_idempotent(
        self,
        *,
        trial_id: str,
        route: str,
        key: str,
        body: dict[str, Any],
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        self.calls.append((route, key, body))
        return await operation()

    async def doctor(self) -> dict[str, Any]:
        return {"ready": True}

    async def create(self, body: CreateTrialInput, *, key: str) -> dict[str, Any]:
        return {"trial_id": body.trial_id or "trial-generated", "key": key}

    async def get(self, trial_id: str) -> dict[str, Any]:
        return {"trial_id": trial_id}

    async def turn(self, trial_id: str, body: TurnInput) -> dict[str, Any]:
        return {"trial_id": trial_id, "assistant": body.message}

    async def confirm_product(self, trial_id: str) -> dict[str, Any]:
        return {"trial_id": trial_id, "confirmed": True}

    async def synthesize_icps(self, trial_id: str) -> dict[str, Any]:
        return {"trial_id": trial_id, "proposals": []}

    async def confirm_icp(self, trial_id: str, proposal: int) -> dict[str, Any]:
        return {"trial_id": trial_id, "proposal": proposal}

    async def add_account(self, trial_id: str, body: AccountInput) -> dict[str, Any]:
        if self.raise_readiness:
            raise TrialReadinessOverrideRequired(("coverage_below_floor",))
        return {"trial_id": trial_id, "domain": body.domain}

    async def research(
        self,
        trial_id: str,
        account_id: UUID,
        body: ResearchInput,
    ) -> dict[str, Any]:
        return {
            "trial_id": trial_id,
            "account_id": str(account_id),
            "action": body.action,
        }

    async def events(self, trial_id: str) -> dict[str, Any]:
        return {"trial_id": trial_id, "events": []}

    async def cost(self, trial_id: str) -> dict[str, Any]:
        return {"trial_id": trial_id, "realized_credits": 0}

    async def report(self, trial_id: str) -> dict[str, Any]:
        return {"trial_id": trial_id, "research_view": None}


def _client(coordinator: _Coordinator) -> TestClient:
    app = FastAPI()
    app.include_router(create_trial_router(coordinator))  # type: ignore[arg-type]
    return TestClient(app)


def test_mutations_require_and_forward_idempotency_keys() -> None:
    coordinator = _Coordinator()
    client = _client(coordinator)

    missing = client.post("/v1/trials/t1/turns", json={"message": "hello"})
    assert missing.status_code == 422

    response = client.post(
        "/v1/trials/t1/turns",
        json={"message": "hello"},
        headers={"Idempotency-Key": "turn-1"},
    )
    assert response.status_code == 200
    assert response.json()["assistant"] == "hello"
    assert coordinator.calls == [("clue_trial.turn", "turn-1", {"message": "hello"})]


def test_route_set_covers_create_resume_stage0_account_research_and_report() -> None:
    coordinator = _Coordinator()
    client = _client(coordinator)
    mutation_headers = {"Idempotency-Key": "test-key"}
    account_id = "11111111-1111-1111-1111-111111111111"

    assert client.get("/v1/trial/doctor").json()["ready"] is True
    assert (
        client.post(
            "/v1/trials",
            json={
                "trial_id": "trial-test",
                "company_name": "Acme",
                "website": "https://acme.example",
                "product_name": "Product",
                "project_name": "Project",
            },
            headers=mutation_headers,
        ).status_code
        == 200
    )
    assert client.get("/v1/trials/trial-test").status_code == 200
    assert (
        client.post(
            "/v1/trials/trial-test/product:confirm",
            headers=mutation_headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/trials/trial-test/icps:synthesize",
            headers=mutation_headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/trials/trial-test/icps/1:confirm",
            headers=mutation_headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/trials/trial-test/accounts",
            json={
                "icp_key": "icp",
                "icp_version": 1,
                "domain": "target.example",
            },
            headers=mutation_headers,
        ).status_code
        == 200
    )
    research = client.post(
        f"/v1/trials/trial-test/accounts/{account_id}:research",
        json={"action": "preview"},
        headers=mutation_headers,
    )
    assert research.status_code == 200
    assert research.json()["action"] == "preview"
    assert client.get("/v1/trials/trial-test/events").status_code == 200
    assert client.get("/v1/trials/trial-test/cost").status_code == 200
    assert client.get("/v1/trials/trial-test/report").status_code == 200


def test_readiness_pause_is_a_structured_conflict() -> None:
    coordinator = _Coordinator()
    coordinator.raise_readiness = True
    response = _client(coordinator).post(
        "/v1/trials/trial-test/accounts",
        json={
            "icp_key": "icp",
            "icp_version": 1,
            "domain": "target.example",
        },
        headers={"Idempotency-Key": "account-1"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "readiness_override_required",
        "message": (
            "Stage 0 is not ready for provider spend; supply an explicit human override reason"
        ),
        "reason_codes": ["coverage_below_floor"],
    }


def test_cli_source_is_http_only() -> None:
    """The trial CLI — and every ``scripts/`` module it reaches — imports no business domain.

    The check walks the closure rather than the entry file alone: ``clue_trial.py`` imports
    ``scripts/cli_multiline.py``, and a script-local helper that reached a domain package would
    break the HTTP-only contract just as surely as a direct import. This is the single definition
    of the ban — no other test may keep its own copy of the list.
    """
    closure = _http_only_closure("clue_trial")

    # The walk is transitive, not just the entry file (a broken walker would silently pass).
    assert _SCRIPTS / "cli_multiline.py" in closure

    for path in closure:
        source = path.read_text(encoding="utf-8")
        offenders = [
            name
            for name in _BANNED_DOMAIN_PACKAGES
            if f"import {name}" in source or f"from {name}" in source
        ]
        assert not offenders, f"{path.name} breaks the HTTP-only CLI contract: {offenders}"
    assert "urllib.request" in (_SCRIPTS / "clue_trial.py").read_text(encoding="utf-8")


def test_trial_process_includes_trial_and_canonical_c7_routes(tmp_path: Path) -> None:
    app = build_application(
        Settings(
            _env_file=None,
            trial_enabled=True,
            trial_root=str(tmp_path / "trials"),
            c7_research_view_read_enabled=True,
            storage_backend="fs",
            storage_fs_root=str(tmp_path / "artifacts"),
        )
    )
    routes = set(app.openapi()["paths"])

    assert "/v1/trials" in routes
    assert "/v1/trials/{trial_id}/accounts/{account_id}:research" in routes
    assert "/v1/projects/{project_id}/accounts/{account_id}/research-view" in routes


def test_report_export_is_reference_linked_and_secret_free(tmp_path: Path) -> None:
    coordinator = ClueTrialCoordinator(
        settings=Settings(
            _env_file=None,
            trial_enabled=True,
            trial_root=str(tmp_path),
        ),
        root=tmp_path,
    )
    now = "2026-07-31T00:00:00Z"
    coordinator._save_manifest(  # noqa: SLF001 - exercises the local artifact renderer in isolation.
        ClueTrialManifest(
            trial_id="trial-report",
            create_request_sha256="a" * 64,
            created_at=now,
            updated_at=now,
            account_entity_id=uuid4(),
            sumble_receipts=(),
        )
    )
    report = {
        "research_view": {
            "status_summary": {
                "total_statement_count": 1,
                "available_statement_count": 1,
                "stale_statement_count": 0,
                "restricted_statement_count": 0,
                "unknown_section_count": 1,
            },
            "coverage_summary": {
                "required_field_count": 2,
                "filled_field_count": 1,
                "terminal_gap_count": 1,
            },
            "sections": [
                {
                    "kind": "about",
                    "items": [
                        {
                            "item_kind": "statement",
                            "statement_id": "statement-1",
                            "claim_id": "claim-1",
                            "field_key": "core.employee_count",
                            "value_json": 42,
                            "state": {"availability": "available"},
                            "confidence": 0.9,
                        }
                    ],
                },
                {
                    "kind": "committee",
                    "reason_codes": ["no_committee_source"],
                    "items": [],
                },
            ],
        },
        "cost": {"sumble": {"realized_credits": 0, "hard_credit_cap": 3}},
    }
    coordinator._export_inspection_artifacts(  # noqa: SLF001 - renderer contract.
        "trial-report",
        report,
    )
    root = tmp_path / "trial-report"

    assert {
        "claims.json",
        "verification.json",
        "research-view.json",
        "failures.json",
        "sumble-requests.sanitized.jsonl",
        "scorecard.md",
        "report.html",
        "trial-report.json",
    } <= {path.name for path in root.iterdir()}
    rendered = (root / "report.html").read_text(encoding="utf-8")
    assert "statement-1" in rendered
    assert "Empty" in rendered
    assert "Authorization" not in rendered
