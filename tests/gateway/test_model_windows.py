import pytest

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


def test_a_trickling_catalogue_gives_up_at_the_deadline(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """2026-10-05: OpenRouter sent the catalogue a few bytes at a time. Each read beat the socket
    timeout, so the fetch ran 105 s; the deadline bounds the whole read, not each chunk."""
    import time

    from clue_gateway import model_windows

    class Trickle:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            # ``http.client`` on a chunked body: waits until ``size`` bytes have trickled in.
            raise AssertionError("read() would block for the whole trickle")

        def read1(self, size: int = -1) -> bytes:
            del size
            time.sleep(0.05)
            return b" "

    monkeypatch.setattr(model_windows.urllib.request, "urlopen", lambda *a, **k: Trickle())
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        model_windows._fetch_catalogue(deadline_s=0.3)
    assert time.monotonic() - started < 2


def test_a_failed_fetch_is_retried_after_the_cooldown_not_cached_forever(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from clue_gateway import model_windows

    def boom() -> dict[str, int]:
        raise OSError("catalogue down")

    assert resolve_context_window("x-ai/grok-4.6", override=None, fetch=boom) is None
    healthy = {"x-ai/grok-4.6": 500_000}
    # Inside the cooldown a failure is not retried on every turn...
    assert resolve_context_window("x-ai/grok-4.6", override=None, fetch=lambda: healthy) is None
    # ...and once it has passed, the catalogue is read again.
    monkeypatch.setattr(model_windows, "_RETRY_AFTER_S", 0.0)
    assert resolve_context_window("x-ai/grok-4.6", override=None, fetch=lambda: healthy) == 500_000


def test_concurrent_callers_fetch_the_catalogue_once() -> None:
    import threading
    import time

    fetched: list[int] = []

    def slow() -> dict[str, int]:
        fetched.append(1)
        time.sleep(0.2)
        return {"x-ai/grok-4.6": 500_000}

    answers: list[int | None] = []
    threads = [
        threading.Thread(
            target=lambda: answers.append(
                resolve_context_window("x-ai/grok-4.6", override=None, fetch=slow)
            )
        )
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert fetched == [1]
    assert answers == [500_000] * 4


def _no_network() -> dict[str, int]:
    raise AssertionError("a registered model must not reach the catalogue")


def test_a_registered_model_never_reaches_the_catalogue() -> None:
    registry = {"x-ai/grok-4.6": 500_000}
    assert (
        resolve_context_window("x-ai/grok-4.6", override=None, registry=registry, fetch=_no_network)
        == 500_000
    )


def test_the_override_still_wins_over_the_registry() -> None:
    assert (
        resolve_context_window(
            "x-ai/grok-4.6",
            override=200_000,
            registry={"x-ai/grok-4.6": 500_000},
            fetch=_no_network,
        )
        == 200_000
    )


def test_an_unregistered_model_falls_back_to_the_catalogue() -> None:
    assert (
        resolve_context_window(
            "openai/gpt-5-mini",
            override=None,
            registry={"x-ai/grok-4.6": 500_000},
            fetch=lambda: {"openai/gpt-5-mini": 400_000},
        )
        == 400_000
    )
