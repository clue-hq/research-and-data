"""M0.5: the redacting log filter masks secrets without breaking formatting.

Also holds the shared-root-console contract that keeps a process from logging
every line twice (see ``clue_obs.config._ROOT_CONSOLE_OWNED``).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator

import pytest
import structlog

from clue_obs.config import _ROOT_CONSOLE_OWNED, setup
from clue_obs.otel import RedactingFilter, get_logger


def _record(msg: str, args: object) -> logging.LogRecord:
    return logging.LogRecord("clue_research.x", logging.INFO, "f.py", 1, msg, args, None)  # type: ignore[arg-type]


def test_redacting_filter_masks_secret_string_arg() -> None:
    record = _record("calling api with %s", ("sk-live-secret-abcdef0123",))
    assert RedactingFilter().filter(record) is True
    rendered = record.getMessage()
    assert "***REDACTED***" in rendered
    assert "sk-live" not in rendered


def test_redacting_filter_preserves_non_secret_and_numeric_args() -> None:
    record = _record("count=%d label=%s", (5, "hello"))
    RedactingFilter().filter(record)
    assert record.getMessage() == "count=5 label=hello"  # %d still works; benign str kept


def test_get_logger_is_namespaced() -> None:
    assert get_logger("discovery").name == "clue_research.discovery"


# ── the shared root-console slot ──────────────────────────────────────────────
# Regression guard for the design fleet worker writing every line twice (6021
# lines, 3391 unique). Two obs configurators live in that one process —
# ``clue_obs`` at boot, and the design subsystem's ``py_lumen_obs`` the moment a
# design job imports ``lumen_api.main`` — and each used to strip only its OWN
# handlers, so both consoles stayed attached to the root logger.
#
# The sibling is simulated with a hand-stamped handler rather than imported:
# ``subsystems/clue-design/`` is outside the root uv workspace, and the two
# packages deliberately share no imports. What is asserted is exactly the
# contract that spans them — the marker attribute and who may remove it.

_SIBLING_PRIVATE_MARKER = "_lumen_obs_handler"  # py_lumen_obs' own ``_OWNED``


@pytest.fixture
def _isolated_root_logger() -> Iterator[logging.Logger]:
    """Snapshot/restore global logging + structlog state around a real ``setup()``."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_structlog = structlog.get_config()
    root.handlers.clear()
    try:
        yield root
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        root.handlers.extend(saved_handlers)
        root.setLevel(saved_level)
        structlog.configure(**saved_structlog)


def _console_slot_handlers(root: logging.Logger) -> list[logging.Handler]:
    return [h for h in root.handlers if getattr(h, _ROOT_CONSOLE_OWNED, False)]


def test_setup_evicts_a_foreign_obs_console_so_the_process_logs_each_line_once(
    _isolated_root_logger: logging.Logger,
) -> None:
    root = _isolated_root_logger
    foreign = logging.StreamHandler()
    setattr(foreign, _SIBLING_PRIVATE_MARKER, True)
    setattr(foreign, _ROOT_CONSOLE_OWNED, True)
    root.addHandler(foreign)

    setup()

    # Exactly one console in the slot, and it is NOT the one we planted.
    assert _console_slot_handlers(root) == [
        h for h in root.handlers if h is not foreign and getattr(h, _ROOT_CONSOLE_OWNED, False)
    ]
    assert len(_console_slot_handlers(root)) == 1
    assert foreign not in root.handlers


def test_setup_is_idempotent_and_never_stacks_consoles(
    _isolated_root_logger: logging.Logger,
) -> None:
    root = _isolated_root_logger
    setup()
    setup()
    setup()
    assert len(_console_slot_handlers(root)) == 1


def test_setup_leaves_a_foreign_run_file_handler_attached_so_no_event_is_lost(
    _isolated_root_logger: logging.Logger,
) -> None:
    """The console is a shared slot; a sibling's run trace is NOT ours to detach."""
    root = _isolated_root_logger
    sibling_run_file = logging.StreamHandler()
    setattr(sibling_run_file, _SIBLING_PRIVATE_MARKER, True)  # private marker ONLY
    root.addHandler(sibling_run_file)

    setup()

    assert sibling_run_file in root.handlers
    assert len(_console_slot_handlers(root)) == 1


def test_the_real_design_obs_module_and_this_one_share_one_console(
    _isolated_root_logger: logging.Logger,
) -> None:
    """The actual two-package collision, in both orders.

    This is the fleet worker's real shape: ``clue_obs.setup()`` at boot, then
    ``py_lumen_obs.configure()`` when a design job imports ``lumen_api.main``.
    Before the shared slot this left TWO stdout handlers and doubled every line.

    Skipped where the design app is not installed — the platform must build and
    test without ``subsystems/clue-design/``.
    """
    lumen_config = pytest.importorskip("py_lumen_obs.config")
    root = _isolated_root_logger

    def stdout_consoles() -> list[logging.Handler]:
        # By STREAM IDENTITY, not by the ownership marker: a regression that
        # dropped the shared marker from one package would still leave two
        # handlers writing to stdout, and that — not the bookkeeping — is what
        # doubles the log. (pytest's own capture handlers are StreamHandlers
        # too, onto a buffer, so they are filtered out here.)
        return [h for h in root.handlers if getattr(h, "stream", None) is sys.stdout]

    setup()
    lumen_config.configure(mode=None)
    assert len(stdout_consoles()) == 1, "platform-then-design must not stack consoles"

    for handler in list(root.handlers):
        root.removeHandler(handler)

    lumen_config.configure(mode=None)
    setup()
    assert len(stdout_consoles()) == 1, "design-then-platform must not stack consoles"
