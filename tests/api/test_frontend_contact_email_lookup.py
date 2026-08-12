"""FI-2 Slice 10 reconciliation and truthful HTTP capability states."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from clue_api.frontend_read.contact_email_lookup import (
    EmailLookupState,
    EmailResolution,
    ProviderState,
    reconcile_email_lookup,
)
from clue_api.projections_app import create_projections_app
from clue_config import load_settings


def test_matching_provider_emails_collapse_with_both_sources() -> None:
    lookup_id = uuid.uuid4()
    view = reconcile_email_lookup(
        lookup_id,
        (
            ("exa_websets", ProviderState.AVAILABLE, "Dana@Example.com"),
            ("sumble_people", ProviderState.AVAILABLE, "dana@example.com"),
        ),
    )

    assert view.state is EmailLookupState.AVAILABLE
    assert view.resolution is EmailResolution.MATCHED
    assert [item.value for item in view.emails] == ["dana@example.com"]
    assert [source.label for source in view.emails[0].sources] == ["Exa", "Sumble"]


def test_conflicting_provider_emails_remain_source_labelled() -> None:
    view = reconcile_email_lookup(
        uuid.uuid4(),
        (
            ("exa_websets", ProviderState.AVAILABLE, "dana@acme.com"),
            ("sumble_people", ProviderState.AVAILABLE, "dana@acme.ai"),
        ),
    )

    assert view.state is EmailLookupState.AVAILABLE
    assert view.resolution is EmailResolution.CONFLICT
    assert [(item.value, item.sources[0].label) for item in view.emails] == [
        ("dana@acme.ai", "Sumble"),
        ("dana@acme.com", "Exa"),
    ]


def test_one_result_survives_other_source_no_result() -> None:
    view = reconcile_email_lookup(
        uuid.uuid4(),
        (
            ("exa_websets", ProviderState.AVAILABLE, "dana@acme.com"),
            ("sumble_people", ProviderState.NO_RESULT, None),
        ),
    )
    assert view.state is EmailLookupState.AVAILABLE
    assert view.resolution is EmailResolution.SINGLE_SOURCE
    assert [item.value for item in view.emails] == ["dana@acme.com"]


def test_no_result_is_distinct_from_unavailable_and_failure() -> None:
    lookup_id = uuid.uuid4()
    no_result = reconcile_email_lookup(
        lookup_id,
        (
            ("exa_websets", ProviderState.NO_RESULT, None),
            ("sumble_people", ProviderState.NO_RESULT, None),
        ),
    )
    unavailable = reconcile_email_lookup(
        lookup_id,
        (
            ("exa_websets", ProviderState.NO_RESULT, None),
            ("sumble_people", ProviderState.UNAVAILABLE, None),
        ),
    )
    failed = reconcile_email_lookup(
        lookup_id,
        (
            ("exa_websets", ProviderState.FAILED, None),
            ("sumble_people", ProviderState.NO_RESULT, None),
        ),
    )

    assert no_result.state is EmailLookupState.NOT_FOUND
    assert no_result.resolution is EmailResolution.NONE
    assert unavailable.state is EmailLookupState.UNAVAILABLE
    assert failed.state is EmailLookupState.FAILED
    assert failed.retryable is True

    contract_error = reconcile_email_lookup(
        lookup_id,
        (
            ("exa_websets", ProviderState.CONTRACT_ERROR, None),
            ("sumble_people", ProviderState.NO_RESULT, None),
        ),
    )
    assert contract_error.state is EmailLookupState.FAILED
    assert contract_error.resolution is EmailResolution.FAILED
    assert contract_error.retryable is False


def test_pending_provider_keeps_partial_result_visible_and_lookup_pending() -> None:
    view = reconcile_email_lookup(
        uuid.uuid4(),
        (
            ("exa_websets", ProviderState.AVAILABLE, "dana@acme.com"),
            ("sumble_people", ProviderState.WAITING_EXTERNAL, None),
        ),
    )
    assert view.state is EmailLookupState.PENDING
    assert view.resolution is EmailResolution.PENDING
    assert [item.value for item in view.emails] == ["dana@acme.com"]


def test_http_lookup_is_honestly_unavailable_when_capability_not_wired() -> None:
    settings = load_settings(_env_file=None, frontend_read_enabled=True)
    app = create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=settings,
        manage_db_lifespan=False,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/frontend/v1/accounts/{uuid.uuid4()}/contacts/{uuid.uuid4()}/email-lookup",
            headers={"X-Workspace-Id": "workspace"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EMAIL_LOOKUP_UNAVAILABLE"
