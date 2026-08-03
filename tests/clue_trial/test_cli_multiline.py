"""Unit tests for the operator-CLI multiline input helpers (`/paste`, `/file`).

The helpers live in ``scripts/cli_multiline.py`` so both trial CLIs share one implementation and
neither has to be driven by a real terminal to be tested. ``scripts/`` is not an installed package
(the CLIs run as ``uv run python scripts/<name>.py``, which puts ``scripts/`` on ``sys.path``), so
the module is loaded here from its file path rather than imported by name.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterable
from pathlib import Path
from types import ModuleType

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cli_multiline.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cli_multiline", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli_multiline = _load()


def _reader(lines: Iterable[str]) -> Callable[[], str]:
    """A line source that raises EOFError once exhausted, exactly like ``input()``."""
    pending = list(lines)

    def _read_line() -> str:
        if not pending:
            raise EOFError
        return pending.pop(0)

    return _read_line


def test_paste_joins_lines_until_the_terminator() -> None:
    read_line = _reader(["We sell to neurosurgeons.", "US only.", ".", "not consumed"])

    assert cli_multiline.read_pasted_message(read_line) == "We sell to neurosurgeons.\nUS only."
    assert read_line() == "not consumed"


def test_paste_preserves_blank_lines_and_leading_indentation_inside_the_block() -> None:
    read_line = _reader(["Product brief", "", "  - indented bullet", "."])

    assert cli_multiline.read_pasted_message(read_line) == "Product brief\n\n  - indented bullet"


def test_paste_terminator_tolerates_trailing_whitespace() -> None:
    read_line = _reader(["one line", ".  "])

    assert cli_multiline.read_pasted_message(read_line) == "one line"


def test_paste_ends_at_eof_without_a_terminator() -> None:
    assert cli_multiline.read_pasted_message(_reader(["first", "second"])) == "first\nsecond"


def test_empty_paste_is_refused() -> None:
    with pytest.raises(cli_multiline.MultilineInputError, match="produced no text"):
        cli_multiline.read_pasted_message(_reader(["."]))


def test_whitespace_only_paste_is_refused() -> None:
    with pytest.raises(cli_multiline.MultilineInputError, match="produced no text"):
        cli_multiline.read_pasted_message(_reader(["   ", "", "."]))


def test_oversize_paste_is_refused_with_the_cap_in_the_message() -> None:
    oversize = "x" * (cli_multiline.MAX_MESSAGE_BYTES + 1)

    with pytest.raises(cli_multiline.MultilineInputError, match="16384 bytes"):
        cli_multiline.read_pasted_message(_reader([oversize, "."]))


def test_file_is_sent_as_one_message(tmp_path: Path) -> None:
    path = tmp_path / "brief.md"
    path.write_text("# Brief\n\nline one\nline two\n", encoding="utf-8")

    assert cli_multiline.read_file_message(str(path)) == "# Brief\n\nline one\nline two"


def test_file_path_is_unquoted_and_user_expanded(tmp_path: Path) -> None:
    path = tmp_path / "brief with spaces.md"
    path.write_text("body", encoding="utf-8")

    assert cli_multiline.read_file_message(f'  "{path}" ') == "body"
    assert cli_multiline.read_file_message(f"'{path}'") == "body"


def test_missing_path_argument_is_refused() -> None:
    with pytest.raises(cli_multiline.MultilineInputError, match="needs a path"):
        cli_multiline.read_file_message("   ")


def test_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(cli_multiline.MultilineInputError, match="no such file"):
        cli_multiline.read_file_message(str(tmp_path / "absent.md"))


def test_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(cli_multiline.MultilineInputError, match="not a regular file"):
        cli_multiline.read_file_message(str(tmp_path))


def test_empty_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.md"
    path.write_text("\n  \n", encoding="utf-8")

    with pytest.raises(cli_multiline.MultilineInputError, match="produced no text"):
        cli_multiline.read_file_message(str(path))


def test_oversize_file_is_refused_before_it_is_read(tmp_path: Path) -> None:
    path = tmp_path / "huge.md"
    path.write_bytes(b"x" * (cli_multiline.MAX_MESSAGE_BYTES + 1))

    with pytest.raises(cli_multiline.MultilineInputError, match="16384 bytes"):
        cli_multiline.read_file_message(str(path))


def test_non_utf8_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "binary.bin"
    path.write_bytes(b"\xff\xfe\x00garbage")

    with pytest.raises(cli_multiline.MultilineInputError, match="UTF-8"):
        cli_multiline.read_file_message(str(path))


def test_multiline_input_error_is_a_value_error() -> None:
    # Both CLIs already funnel ValueError back to the prompt instead of ending the session.
    assert issubclass(cli_multiline.MultilineInputError, ValueError)


def test_cap_fits_the_routed_turn_inside_the_model_budgets() -> None:
    # The real bound is not the trial API (which caps nothing) but Stage-0 routing. It used to be
    # an *output* bound: the model echoed the whole message byte-identically into
    # `record_interview_answer.answer`, inside the active profile's `max_output_tokens` (8192).
    # PC-C8 §6a retired that echo — the engine loads the captured bytes and the model sends only
    # offsets — so what 16 KB now bounds is the L7 turn candidate the message becomes and the
    # span the model must reason over. The cap is deliberately left where it is: relaxing it is a
    # context-budget decision (Slice 2 re-denominates layer budgets in tokens), not a free win
    # from the echo going away.
    assert cli_multiline.MAX_MESSAGE_BYTES == 16 * 1024


# NOTE: this module is imported by the HTTP-only `scripts/clue_trial.py`, so it must stay free of
# business-domain imports. That ban is NOT re-asserted here — duplicating the banned-package list
# would let the two copies drift. `tests/api/test_clue_trial_http.py::test_cli_source_is_http_only`
# owns the single list and walks the CLI's whole scripts/-local import closure, which includes this
# module.
