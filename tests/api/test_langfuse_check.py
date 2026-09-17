"""Lane 3 slice 3a, Task 8: the check verb reads the settings, probes the keys, sends no trace."""

from __future__ import annotations

from typing import Any

import pytest

from clue_api.langfuse_check import main
from clue_config import Secrets, Settings


def _secrets(**kwargs: Any) -> Secrets:
    return Secrets(_env_file=None, **kwargs)  # type: ignore[call-arg]


def test_disabled_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([], settings=Settings(_env_file=None, langfuse_enabled=False), secrets=_secrets())
    assert code == 2
    assert "disabled" in capsys.readouterr().out


def test_enabled_without_keys_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([], settings=Settings(_env_file=None, langfuse_enabled=True), secrets=_secrets())
    assert code == 1
    assert "CLUE_LANGFUSE_PUBLIC_KEY" in capsys.readouterr().out


def test_enabled_with_keys_probes_and_reports(capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[dict[str, str]] = []

    def check(*, public_key: str, secret_key: str, host: str) -> bool:
        seen.append({"public_key": public_key, "secret_key": secret_key, "host": host})
        return True

    settings = Settings(
        _env_file=None,
        langfuse_enabled=True,
        langfuse_host="https://cloud.langfuse.com",
        langfuse_environment="lane-test",
    )
    code = main(
        [],
        settings=settings,
        secrets=_secrets(langfuse_public_key="pk", langfuse_secret_key="sk"),
        check=check,
    )
    assert code == 0
    assert seen == [{"public_key": "pk", "secret_key": "sk", "host": "https://cloud.langfuse.com"}]
    out = capsys.readouterr().out
    assert (
        "langfuse: ok" in out and "env=lane-test" in out and "sk" not in out.replace("langfuse", "")
    )


def test_a_refused_key_pair_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [],
        settings=Settings(_env_file=None, langfuse_enabled=True),
        secrets=_secrets(langfuse_public_key="pk", langfuse_secret_key="sk"),
        check=lambda **kwargs: False,
    )
    assert code == 1
    assert "refused" in capsys.readouterr().out
