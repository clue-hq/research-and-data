"""M4.3 static invariants (DB-free): adapters don't import resolvers / each other; registry guards.

The "adapters do not import resolvers or each other" acceptance criterion is machine-enforced by
import-linter Rule 3 (workers independence), in ``tests/test_dependency_contracts.py``. Here we add
a direct source scan (a fast text-level guard) as a backstop, plus the registry's own behaviour.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from clue_research.adapters import (
    AdapterNotRegisteredError,
    PassthroughAdapter,
    clear_adapters,
    get_adapter,
    is_adapter_registered,
    register_adapter,
    registered_adapter_keys,
    span_for,
    unregister_adapter,
)
from clue_research.core import Modality

_ADAPTERS_DIR = Path(__file__).resolve().parents[2] / "src" / "clue_research" / "adapters"


def test_adapters_import_is_hermetic_without_provider_sdks() -> None:
    """Importing the adapters package must NOT eagerly import a provider SDK (pypdf / firecrawl).

    Rule 4 only forbids those SDKs *outside* adapters/; it does not stop an eager top-level import
    *inside* adapters/. The lazy-import-inside-the-method discipline the docstrings rely on (so CI's
    double-driven path needs neither SDK nor key) is machine-checked here: a subprocess masks both
    SDKs (``sys.modules[...] = None`` makes ``import`` raise) and asserts the package still imports,
    so a top-level-import regression fails loud."""
    code = (
        "import sys\n"
        "sys.modules['pypdf'] = None\n"
        "sys.modules['firecrawl'] = None\n"
        "import clue_research.adapters\n"  # must import with both SDKs unavailable
        "print('ok')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_adapters_package_does_not_import_resolvers() -> None:
    """An adapter must never import a resolver (conventions §2; import-linter Rule 3) — a direct
    source scan as a fast backstop to the machine contract."""
    offenders = [
        py.name
        for py in _ADAPTERS_DIR.rglob("*.py")
        if "clue_research.resolvers" in py.read_text()
        or "from clue_research import resolvers" in py.read_text()
    ]
    assert not offenders, f"adapters import resolvers in: {offenders}"


def _passthrough() -> PassthroughAdapter:
    return PassthroughAdapter(modality=Modality.TEXT)


def test_register_and_get_adapter_roundtrip() -> None:
    clear_adapters()
    adapter = _passthrough()
    assert not is_adapter_registered("text")
    register_adapter("text", adapter)
    assert is_adapter_registered("text")
    assert get_adapter("text") is adapter
    assert "text" in registered_adapter_keys()
    unregister_adapter("text")
    assert not is_adapter_registered("text")


def test_get_unregistered_adapter_raises() -> None:
    clear_adapters()
    with pytest.raises(AdapterNotRegisteredError, match="no modality adapter registered"):
        get_adapter("nope")


def test_register_rejects_non_conforming_object() -> None:
    clear_adapters()
    with pytest.raises(TypeError, match="does not satisfy the ModalityAdapter protocol"):
        register_adapter("bad", object())  # type: ignore[arg-type]


def test_span_for_guards_grounding() -> None:
    assert span_for("the cat sat", "cat") == "cat"
    with pytest.raises(ValueError, match="not a substring"):
        span_for("the cat sat", "dog")
