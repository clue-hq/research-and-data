"""The driver's page-writer step: when it writes, and what a failure does to the job."""

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

import clue_api.arv2.page_writer_runtime as runtime
from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler
from clue_api.arv2.page_writer_runtime import PageWriterModels
from clue_api.arv2.quality_results import QualityJobOutcome
from clue_config import Settings
from tests.arv2.test_account_research_driver import (
    FakeArtifacts,
    FakeClients,
    FakeConnFactory,
    FakeModels,
    FakeWriter,
    _finalizes_at_once,
)

MODELS = PageWriterModels(call_for=lambda scope: None, model_id="test/writer")  # type: ignore[arg-type,return-value]


def handler(models: PageWriterModels | None) -> Arv2AccountResearchWorkHandler:
    return Arv2AccountResearchWorkHandler(
        settings=Settings(_env_file=None),
        conn_factory=FakeConnFactory(),
        artifacts=FakeArtifacts(),
        storage=object(),  # type: ignore[arg-type]
        clients=FakeClients(),  # type: ignore[arg-type]
        model_provider=FakeModels(_finalizes_at_once()),
        model_id="x-ai/grok-4.6",
        writer=FakeWriter(),  # type: ignore[arg-type]
        page_writer=models,
    )


def composition(recipe: int, *, person: bool = False) -> Any:
    refs: dict[str, Any] = {"quality_recipe_version": recipe}
    if person:
        refs["parent_job_id"] = str(uuid4())
    scope = SimpleNamespace(
        catalog_version="v4",
        input_refs=refs,
        job_id=uuid4(),
        workspace_id="ws",
        person_subject_id=uuid4() if person else None,
    )
    return SimpleNamespace(scope=scope, run=SimpleNamespace(context_id=uuid4()))


def outcome(status: str = "completed") -> QualityJobOutcome:
    return QualityJobOutcome(uuid4(), status, "key", object(), None)  # type: ignore[arg-type]


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> tuple[()]:
        calls.append(kwargs)
        if kwargs["scope"].input_refs.get("fail"):
            raise ValueError("writer refused")
        return ()

    monkeypatch.setattr(runtime, "write_job_pages", fake)
    return calls


def test_older_recipes_leave_writing_to_the_researcher(writes: list[dict[str, Any]]) -> None:
    result = outcome()
    assert asyncio.run(handler(MODELS)._write_pages(composition(24), result)) is result
    assert writes == []


def test_a_completed_recipe_25_job_gets_its_pages_written(writes: list[dict[str, Any]]) -> None:
    job = composition(25)
    result = outcome()
    assert asyncio.run(handler(MODELS)._write_pages(job, result)) is result
    assert len(writes) == 1
    assert writes[0]["scope"] is job.scope and writes[0]["models"] is MODELS
    assert writes[0]["context_id"] == job.run.context_id


def test_research_that_did_not_complete_is_not_written_up(writes: list[dict[str, Any]]) -> None:
    result = outcome("failed")
    assert asyncio.run(handler(MODELS)._write_pages(composition(25), result)) is result
    assert writes == []


def test_a_writer_failure_sends_the_job_to_review(writes: list[dict[str, Any]]) -> None:
    job = composition(25)
    job.scope.input_refs["fail"] = True
    settled = asyncio.run(handler(MODELS)._write_pages(job, outcome()))
    assert settled.status == "needs_review" and settled.failure_code == "page_writer_failed"


def test_an_uncomposed_writer_sends_the_job_to_review(writes: list[dict[str, Any]]) -> None:
    settled = asyncio.run(handler(None)._write_pages(composition(25), outcome()))
    assert settled.status == "needs_review" and settled.failure_code == "page_writer_not_composed"
    assert writes == []


@pytest.mark.parametrize("imported", [False, True])
def test_recipe_26_person_defers_its_page_until_the_parent_imports(
    writes: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, imported: bool
) -> None:
    import clue_api.arv2.quality_person_release as release

    async def ready(conn: Any, scope: Any) -> bool:
        return imported

    monkeypatch.setattr(release, "parent_dossier_ready", ready)
    settled = asyncio.run(handler(MODELS)._write_pages(composition(26, person=True), outcome()))
    assert settled.status == "completed"
    if imported:
        assert len(writes) == 1 and settled.deferred_pages == ()
    else:
        assert writes == [] and settled.deferred_pages == ("contact",)


def test_a_recipe_25_person_still_writes_its_page_at_once(
    writes: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    import clue_api.arv2.quality_person_release as release

    async def ready(conn: Any, scope: Any) -> bool:
        return False

    monkeypatch.setattr(release, "parent_dossier_ready", ready)
    settled = asyncio.run(handler(MODELS)._write_pages(composition(25, person=True), outcome()))
    assert len(writes) == 1 and settled.deferred_pages == ()


def work_context() -> Any:
    return SimpleNamespace(stop_requested=asyncio.Event(), lease_lost=asyncio.Event())


async def leased(conn: Any) -> None:
    return None


@pytest.fixture
def rewrites(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    import clue_api.arv2.quality_generation as generation

    seen: dict[str, list[Any]] = {"rewrites": [], "settled": []}

    async def fake_rewrite(**kwargs: Any) -> dict[str, Any]:
        seen["rewrites"].append(kwargs)
        if kwargs["scope"].input_refs.get("fail"):
            raise ValueError("writer refused")
        return {"applied": True}

    async def fake_reconcile(conn: Any, **kwargs: Any) -> bool:
        seen["settled"].append(kwargs)
        return True

    monkeypatch.setattr(runtime, "rewrite_account_pages", fake_rewrite)
    monkeypatch.setattr(generation, "reconcile_generation", fake_reconcile)
    return seen


def test_the_account_rewrite_runs_the_writer_for_the_revision(
    rewrites: dict[str, list[Any]],
) -> None:
    job = composition(25)
    generation_id = uuid4()
    out = asyncio.run(
        handler(MODELS)._rewrite_account(
            work_context(), job.scope, job.run.context_id, generation_id, 3, leased
        )
    )
    assert out.outcome == "completed"
    call = rewrites["rewrites"][0]
    assert call["generation_id"] == generation_id and call["revision"] == 3
    assert call["models"] is MODELS and rewrites["settled"] == []


@pytest.mark.parametrize("recipe", [25, 26])
def test_the_final_step_passes_the_deferred_contact_pages(
    rewrites: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch, recipe: int
) -> None:
    job = composition(recipe)
    person = composition(recipe, person=True).scope
    asked: list[Any] = []

    async def deferred(self: Any, scope: Any, generation_id: Any) -> tuple[Any, ...]:
        asked.append(generation_id)
        return (person,)

    monkeypatch.setattr(Arv2AccountResearchWorkHandler, "_deferred_contacts", deferred)
    generation_id = uuid4()
    out = asyncio.run(
        handler(MODELS)._rewrite_account(
            work_context(), job.scope, job.run.context_id, generation_id, 3, leased
        )
    )
    assert out.outcome == "completed"
    passed = rewrites["rewrites"][0].get("deferred", ())
    assert passed == ((person,) if recipe >= 26 else ())
    assert asked == ([generation_id] if recipe >= 26 else [])


def test_a_failed_rewrite_sends_the_generation_to_review(
    rewrites: dict[str, list[Any]],
) -> None:
    job = composition(25)
    job.scope.input_refs["fail"] = True
    out = asyncio.run(
        handler(MODELS)._rewrite_account(
            work_context(), job.scope, job.run.context_id, uuid4(), 3, leased
        )
    )
    assert out.outcome == "failed"
    assert rewrites["settled"][0]["needs_review"] is True
    assert rewrites["settled"][0]["expected_revision"] == 3


def test_an_uncomposed_writer_cannot_rewrite(rewrites: dict[str, list[Any]]) -> None:
    job = composition(25)
    out = asyncio.run(
        handler(None)._rewrite_account(
            work_context(), job.scope, job.run.context_id, uuid4(), 3, leased
        )
    )
    assert out.outcome == "failed" and rewrites["rewrites"] == []
    assert rewrites["settled"][0]["needs_review"] is True
