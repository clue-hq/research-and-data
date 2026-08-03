"""Multiline input helpers shared by the two operator trial CLIs.

Both CLIs read one turn per ``input()`` call, so pasting a multi-paragraph product brief used to
arrive as many separate turns — the agent re-asked questions it had already been told and the run
burned model calls on fragments. These helpers give the operator two explicit ways to send a block
of text as **one** message:

``/paste``     read lines until a line containing only ``.``;
``/file PATH`` send the contents of a UTF-8 text file.

Everything here is pure and stdlib-only (no business-domain imports), so it is unit-testable
without a terminal and safe to import from the HTTP-only ``clue_trial.py`` client.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

#: A line containing only this (trailing whitespace tolerated) ends a ``/paste`` block.
PASTE_TERMINATOR = "."

#: Client-side cap for one assembled message. The trial API sets no maximum of its own, but the
#: real bound is Stage-0 routing. It used to be an *output* bound — the model echoed the whole
#: message byte-identically into ``record_interview_answer.answer`` and the echo had to fit the
#: profile's ``max_output_tokens``. PC-C8 §6a retired the echo: the engine loads the captured bytes
#: from the artifact and the model sends only quote offsets into them. What 16 KB now bounds is the
#: L7 turn candidate the message becomes, and the span the model must reason over to route it. The
#: cap is deliberately unchanged — relaxing it is a context-budget decision, not a free consequence
#: of the echo going away — and it still keeps an accidental ``/file`` of a log or a binary from
#: being shipped as a conversation turn.
MAX_MESSAGE_BYTES = 16 * 1024


class MultilineInputError(ValueError):
    """A ``/paste`` or ``/file`` request that cannot become one chat message.

    A ``ValueError`` on purpose: both CLIs already print a ``ValueError`` and hand the prompt back
    rather than ending the session.
    """


def _finalize(text: str, *, origin: str) -> str:
    """Trim, then reject an empty or oversize block before it becomes a turn."""
    message = text.strip()
    if not message:
        raise MultilineInputError(f"{origin} produced no text to send.")
    size = len(message.encode("utf-8"))
    if size > MAX_MESSAGE_BYTES:
        raise MultilineInputError(
            f"{origin} is {size} bytes; one message is capped at {MAX_MESSAGE_BYTES} bytes. "
            "Send it in smaller parts."
        )
    return message


def read_pasted_message(read_line: Callable[[], str]) -> str:
    """Collect lines from ``read_line`` into one message.

    Stops at the first line that is only ``PASTE_TERMINATOR`` (trailing whitespace tolerated), or
    at EOF. Blank lines and indentation inside the block are preserved verbatim; only the outer
    whitespace of the assembled block is trimmed.
    """
    lines: list[str] = []
    while True:
        try:
            line = read_line()
        except EOFError:
            break
        if line.strip() == PASTE_TERMINATOR:
            break
        lines.append(line.rstrip("\n"))
    return _finalize("\n".join(lines), origin="/paste")


def _resolve(raw_path: str) -> Path:
    """Validate an operator-typed path: unquoted, user-expanded, existing, and a regular file."""
    candidate = raw_path.strip()
    for quote in ('"', "'"):
        if len(candidate) >= 2 and candidate.startswith(quote) and candidate.endswith(quote):
            candidate = candidate[1:-1].strip()
    if not candidate:
        raise MultilineInputError("/file needs a path, e.g. /file ./brief.md")
    path = Path(candidate).expanduser()
    if not path.exists():
        raise MultilineInputError(f"no such file: {path}")
    if not path.is_file():
        raise MultilineInputError(f"not a regular file: {path}")
    return path


def read_file_message(raw_path: str) -> str:
    """Read a UTF-8 text file as one message.

    The size cap is checked against the file's own size *before* the file is read, so a huge or
    binary file is refused rather than loaded into memory.
    """
    path = _resolve(raw_path)
    # stat() is inside the guard with the read: an unreadable/vanished file must refuse this one
    # command, not raise an OSError through the loop and end the session.
    try:
        size = path.stat().st_size
        if size > MAX_MESSAGE_BYTES:
            raise MultilineInputError(
                f"{path} is {size} bytes; one message is capped at {MAX_MESSAGE_BYTES} bytes."
            )
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise MultilineInputError(f"{path} is not UTF-8 text; send a plain-text file.") from exc
    except OSError as exc:
        raise MultilineInputError(f"cannot read {path}: {exc}") from exc
    return _finalize(text, origin=f"/file {path}")


#: One-line reminder printed with each CLI's command list.
HELP_LINE = (
    "Multi-line input: /paste (then paste, and end with a line containing only .) or "
    "/file PATH (send a text file as one message)."
)

__all__ = [
    "HELP_LINE",
    "MAX_MESSAGE_BYTES",
    "PASTE_TERMINATOR",
    "MultilineInputError",
    "read_file_message",
    "read_pasted_message",
]
