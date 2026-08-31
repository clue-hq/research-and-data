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
    """Both recipes, not just the subsystem's own. W1.6 landed the brief stage's
    `LUMEN_INGESTION_BRIEF=1` in `subsystems/clue-design/.env.example` alone,
    which left the monorepo recipe — the one that actually configures the design
    API in this repo — publishing briefless kits off every forced render."""
    monorepo_recipe = _env_values(MONOREPO_ROOT / ".env.example")
    assert monorepo_recipe["OPENROUTER_API_KEY"] == '"${CLUE_OPENROUTER_API_KEY}"'

    for recipe in (MONOREPO_ROOT / ".env.example", DESIGN_ROOT / ".env.example"):
        values = _env_values(recipe)
        assert values["LUMEN_INGESTION_VISION"] == "1", recipe
        assert values["LUMEN_INGESTION_DESCRIBE"] == "1", recipe
        assert values["LUMEN_INGESTION_BRIEF"] == "1", recipe
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


def test_the_platform_spelling_of_the_key_still_keys_the_design_subsystem(monkeypatch) -> None:
    """W5/R2-B red case: a `.env` that spells ONLY `CLUE_OPENROUTER_API_KEY`.

    That is the stock monorepo shape the W5 acceptance run hit. Before the fallback the
    design side resolved nothing, so the ad-DNA distiller wrote no card, pre-generation
    produced nothing, and the job still said `succeeded`. The platform namespaces its
    settings under `CLUE_`; the design subsystem never has. One shared resolution now
    bridges them, in the settings package rather than at any call site.
    """
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("CLUE_OPENROUTER_API_KEY", "platform-spelled-key")

    assert Settings(_env_file=None).openrouter_api_key == "platform-spelled-key"


def test_the_design_spelling_of_the_key_wins_when_both_are_set(monkeypatch) -> None:
    """Precedence, not replacement: the design name is still THE name."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "design-spelled-key")
    monkeypatch.setenv("CLUE_OPENROUTER_API_KEY", "platform-spelled-key")

    assert Settings(_env_file=None).openrouter_api_key == "design-spelled-key"


def test_a_blank_design_key_does_not_shadow_a_real_platform_key(monkeypatch) -> None:
    """`OPENROUTER_API_KEY=` means "not configured", exactly as `_blank_is_unset` reads it.

    This is the same silent-inertness in a second costume: a half-migrated `.env` that
    carries the line but no value, or the repo recipe's `"${CLUE_OPENROUTER_API_KEY}"`
    shell-expanded before the platform key was exported.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "   ")
    monkeypatch.setenv("CLUE_OPENROUTER_API_KEY", "platform-spelled-key")

    assert Settings(_env_file=None).openrouter_api_key == "platform-spelled-key"


def test_neither_spelling_set_stays_keyless(monkeypatch) -> None:
    """No key is still no key — the fallback invents nothing."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CLUE_OPENROUTER_API_KEY", raising=False)

    assert Settings(_env_file=None).openrouter_api_key == ""


def test_the_whole_design_gateway_resolves_through_the_one_field(monkeypatch) -> None:
    """The ad lane is keyed by the same resolution as its older neighbours, not its own.

    `resolve_distiller` was the R2-B casualty; `resolve_describer` is the neighbour that
    proves the resolution is shared rather than lane-local.
    """
    from lumen_ingestion.ad_library.distill import OpenRouterAdDnaDistiller, resolve_distiller

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("CLUE_OPENROUTER_API_KEY", "platform-spelled-key")
    resolved = Settings(_env_file=None)

    monkeypatch.setattr(settings, "openrouter_api_key", resolved.openrouter_api_key)
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True)
    monkeypatch.setattr(settings, "lumen_ingestion_describe", True)

    distiller = resolve_distiller()
    assert isinstance(distiller, OpenRouterAdDnaDistiller)
    assert distiller.active is True
    assert pipeline.resolve_describer().active is True


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
