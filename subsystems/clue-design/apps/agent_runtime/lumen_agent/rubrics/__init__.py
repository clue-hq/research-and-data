"""Shared review rubrics — one artifact, many readers (founder ruling D-F7).

D-F7 is a rule about WHERE review knowledge lives: *"Clone/audit review knowledge lives in a
SHARED RUBRIC artifact, never inside one agent's private prompt."* The web lane has two possible
reviewers — the `lumen-web-reviewer` subagent, and the orchestrator self-reviewing when the
lane's fast-loop flag quarantines it — and the ruling's closing line is the whole design
constraint: **the flag changes WHO checks, never WHAT is checked.**

So the rubric is a FILE, not a string constant in a prompt builder. Two prompt builders reading
one file cannot drift; two prompt builders each holding "the rubric" as a literal will, on the
first day somebody improves one of them. Editing `clone-review-rubric.md` changes both readers,
and a test pins that they render the same bytes.

The file carries its own version in an HTML comment header, and everything after the
`--- rubric ---` marker is what a reader receives verbatim. The header is for the humans who
maintain the file (why it exists, that its wording is founder-reviewed); shipping it into a
prompt would be spending tokens on instructions to nobody.
"""

from __future__ import annotations

from pathlib import Path

#: The marker separating the maintainers' header from the rubric a reader receives.
RUBRIC_MARKER = "--- rubric ---"

#: Where the artifact lives. Module-level so a test can point the loader at a different file and
#: prove that BOTH compositions follow it — the "no private copy" guarantee, checked rather than
#: asserted in a comment.
CLONE_REVIEW_RUBRIC_PATH = Path(__file__).resolve().parent / "clone-review-rubric.md"


class RubricMissing(RuntimeError):
    """The rubric artifact is not on disk. Loud, because a review with no rubric is not a review."""


def load_clone_review_rubric(path: Path | None = None) -> str:
    """The rubric text, exactly as both readers receive it.

    Read on every call rather than cached: a rubric is loaded at most twice per turn (once per
    prompt), the file is a couple of kilobytes, and a cache is the mechanism by which an edited
    artifact stops reaching one of its readers — which is the single failure mode this module
    exists to prevent.
    """
    source = path or CLONE_REVIEW_RUBRIC_PATH
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as error:
        raise RubricMissing(
            f"the shared clone-review rubric could not be read at {source}: {error}. "
            "Both the reviewer subagent and the orchestrator's self-review compose from this "
            "one artifact, so neither can be built without it"
        ) from error
    _, marker, body = raw.partition(RUBRIC_MARKER)
    if not marker:
        # No marker means somebody removed the header convention rather than the rubric; the
        # whole file is then the rubric, which is the conservative reading.
        return raw.strip()
    return body.strip()


def clone_review_rubric_version(path: Path | None = None) -> int:
    """The artifact's declared version, or 0 when it declares none."""
    source = path or CLONE_REVIEW_RUBRIC_PATH
    try:
        for line in source.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("version:"):
                return int(stripped.split(":", 1)[1].strip())
    except (OSError, ValueError):
        return 0
    return 0


__all__ = [
    "CLONE_REVIEW_RUBRIC_PATH",
    "RUBRIC_MARKER",
    "RubricMissing",
    "clone_review_rubric_version",
    "load_clone_review_rubric",
]
