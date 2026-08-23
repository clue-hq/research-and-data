from __future__ import annotations

from pathlib import Path

from lumen_ingestion import pipeline
from lumen_ingestion.capture import pdf as pdf_capture
from lumen_ingestion.capture.pdf_vision import NullPdfVision, OpenRouterPdfVision
from lumen_ingestion.describe import OpenRouterDescriber
from py_lumen_config import settings
from py_lumen_config.config import Settings

DESIGN_ROOT = Path(__file__).resolve().parents[3]
MONOREPO_ROOT = Path(__file__).resolve().parents[5]


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_deployment_recipes_enable_ingestion_vision_and_descriptions() -> None:
    monorepo_recipe = _env_values(MONOREPO_ROOT / ".env.example")
    assert monorepo_recipe["OPENROUTER_API_KEY"] == '"${CLUE_OPENROUTER_API_KEY}"'

    for recipe in (MONOREPO_ROOT / ".env.example", DESIGN_ROOT / ".env.example"):
        values = _env_values(recipe)
        assert values["LUMEN_INGESTION_VISION"] == "1", recipe
        assert values["LUMEN_INGESTION_DESCRIBE"] == "1", recipe
        assert "OPENROUTER_API_KEY" in values, recipe


def test_subsystem_intrinsic_defaults(monkeypatch) -> None:
    """PDF vision stays off intrinsically; asset DESCRIBE is on by default
    since design-quality Wave 1 (founder ruling R4) — a brand card whose image
    menu is bare `img.N` rows is useless to the agent. The gate that keeps a
    deterministic/test context silent is key presence, asserted next door in
    `test_enabled_assists_fail_soft_without_openrouter_key`."""
    monkeypatch.delenv("LUMEN_INGESTION_VISION", raising=False)
    monkeypatch.delenv("LUMEN_INGESTION_DESCRIBE", raising=False)
    isolated = Settings(_env_file=None)
    assert isolated.lumen_ingestion_vision is False
    assert isolated.lumen_ingestion_describe is True


def test_enabled_assists_fail_soft_without_openrouter_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "lumen_ingestion_vision", True)
    monkeypatch.setattr(settings, "lumen_ingestion_describe", True)
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    vision = pipeline.resolve_pdf_vision()
    describer = pipeline.resolve_describer()

    assert isinstance(vision, NullPdfVision)
    assert isinstance(describer, OpenRouterDescriber)
    assert describer.active is False


def test_vision_resolver_uses_openrouter_when_flag_and_key_are_present(monkeypatch) -> None:
    monkeypatch.setattr(settings, "lumen_ingestion_vision", True)
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    assert isinstance(pipeline.resolve_pdf_vision(), OpenRouterPdfVision)


def test_default_pdf_extractor_threads_the_resolved_vision(monkeypatch) -> None:
    sentinel = object()
    seen: dict[str, object] = {}

    def fake_extract(*args, **kwargs):
        seen.update(kwargs)
        return "extracted"

    monkeypatch.setattr(pipeline, "resolve_pdf_vision", lambda: sentinel)
    monkeypatch.setattr(pdf_capture, "extract_pdf_evidence", fake_extract)

    result = pipeline._default_extract_pdf(
        b"pdf",
        "kit.pdf",
        core=object(),
        store_root="/tmp/cache",
        reporter=lambda _stage, _progress: None,
    )

    assert result == "extracted"
    assert seen["vision"] is sentinel
