"""A failed turn is named for what the provider did, not for the SDK class that carried the news.

``permission_denied_error`` tells a human nothing; ``provider_refused:openrouter:key_limit``
tells them the account hit its cap. The turn row and the incident record then read the same code.
"""

from __future__ import annotations

from clue_agents.runtime import _error_code


class PermissionDeniedError(Exception):
    status_code = 403

    def __init__(self) -> None:
        super().__init__(
            "Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit)'}}"
        )


class WeirdThingHappened(Exception): ...


def test_a_classified_provider_failure_becomes_the_provider_code() -> None:
    assert _error_code(PermissionDeniedError()) == "provider_refused:openrouter:key_limit"


def test_anything_else_keeps_the_class_name_code() -> None:
    assert _error_code(WeirdThingHappened()) == "weird_thing_happened"
