"""C7.8 default-off, independently reversible HTTP activation contract."""

from __future__ import annotations

from clue_api.research_view_api import build_research_view_router
from clue_config import Settings, load_settings


def _paths(settings: Settings) -> set[tuple[str, str]]:
    router = build_research_view_router(
        composer=None,  # type: ignore[arg-type]
        snapshots=None,  # type: ignore[arg-type]
        evidence_access=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        conn_factory=None,  # type: ignore[arg-type]
        settings=settings,
    )
    return {(method, route.path) for route in router.routes for method in (route.methods or ())}


def _settings(**kwargs: bool) -> Settings:
    return load_settings(_env_file=None, **kwargs)


def test_all_c7_http_routes_are_absent_by_default() -> None:
    assert _paths(_settings()) == set()


def test_c7_http_capabilities_activate_independently() -> None:
    read = _paths(_settings(c7_research_view_read_enabled=True))
    assert read == {
        ("GET", "/v1/projects/{project_id}/accounts/{account_id}/research-view"),
        ("GET", "/v1/projects/{project_id}/contacts/{contact_id}/research-view"),
        ("GET", "/v1/projects/{project_id}/research-view-status"),
        ("GET", "/v1/research-view-snapshots/{snapshot_id}"),
        (
            "POST",
            "/v1/projects/{project_id}/research-view-owner-references:resolve",
        ),
    }
    assert _paths(_settings(c7_snapshot_compose_enabled=True)) == {
        ("POST", "/v1/research-view-snapshots")
    }
    assert _paths(_settings(c7_recheck_enabled=True)) == {
        ("POST", "/v1/research-view-snapshots/{snapshot_id}/recheck")
    }
    assert _paths(_settings(c7_evidence_actions_enabled=True)) == {
        ("POST", "/v1/research-statements/{statement_id}/evidence-action")
    }


def test_legacy_alias_requires_its_flag_and_the_canonical_capability() -> None:
    alias_only = _paths(_settings(c7_legacy_dossier_alias_enabled=True))
    assert alias_only == set()

    enabled = _paths(
        _settings(
            c7_research_view_read_enabled=True,
            c7_snapshot_compose_enabled=True,
            c7_legacy_dossier_alias_enabled=True,
        )
    )
    assert ("GET", "/v1/projects/{project_id}/accounts/{account_id}/dossier") in enabled
    assert ("GET", "/v1/projects/{project_id}/contacts/{contact_id}/dossier") in enabled
    assert ("POST", "/v1/dossier") in enabled
