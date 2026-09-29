from clue_gateway.model_windows import _reset_cache, resolve_context_window


def setup_function() -> None:
    _reset_cache()


def test_the_catalogue_names_the_window() -> None:
    assert (
        resolve_context_window(
            "x-ai/grok-4.6", override=None, fetch=lambda: {"x-ai/grok-4.6": 500_000}
        )
        == 500_000
    )


def test_an_override_wins_over_the_catalogue() -> None:
    assert (
        resolve_context_window(
            "x-ai/grok-4.6", override=200_000, fetch=lambda: {"x-ai/grok-4.6": 500_000}
        )
        == 200_000
    )


def test_an_unknown_model_or_unreachable_catalogue_is_none_never_a_failure() -> None:
    assert resolve_context_window("x-ai/none", override=None, fetch=lambda: {}) is None

    def boom() -> dict[str, int]:
        raise OSError("catalogue down")

    _reset_cache()
    assert resolve_context_window("x-ai/grok-4.6", override=None, fetch=boom) is None
