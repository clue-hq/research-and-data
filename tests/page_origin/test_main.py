from __future__ import annotations

import pytest

from clue_config import Secrets, Settings
from clue_page_origin.main import build_gate


def test_build_gate_refuses_trust_with_a_secret() -> None:
    settings = Settings(_env_file=None, pages_trust_host_header=True)
    secrets = Secrets(_env_file=None, pages_edge_secret="s")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        build_gate(settings, secrets)


def test_build_gate_dev_and_prod_shapes() -> None:
    dev = build_gate(
        Settings(_env_file=None, pages_trust_host_header=True),
        Secrets(_env_file=None),  # type: ignore[call-arg]
    )
    assert dev is not None
    prod = build_gate(
        Settings(_env_file=None),
        Secrets(_env_file=None, pages_edge_secret="s"),  # type: ignore[call-arg]
    )
    assert prod is not None
