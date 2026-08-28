"""What "this clone is broken" says, and what a repair says back (F3.1, ruling D-F6).

F3.0 gave the registry two columns and left their vocabulary to whoever wrote into them:
``degraded_reason`` on a broken original, ``derived_reason`` on the fragment that replaces it.
The first had exactly one producer (the dead-height detector) and its code was spelled
producer-side; F3.1 adds the first CONSUMER — the repair ladder has to know what it is repairing
in order to say which rung it reached — so the spelling moves here, to the one module both sides
already import (review finding M6). String-matching ``"dead_height"`` in two files is the shape
of a bug that only appears when somebody renames one of them.

**The reason vocabulary stays OPEN.** The CHECK on the column enforces presence and non-emptiness
and nothing else (F3.0 decision 2), because F3.3's behavioural review gate will find brokenness
this detector cannot — a blank mobile viewport, a dead control — and each of those would
otherwise cost a migration. :data:`DEGRADED_REASONS` is therefore the set of codes THIS build
knows how to talk about, not the set a row may hold: :func:`degraded_headline` answers for an
unknown code too, in words that do not pretend to know more than they do.

**A repair's ``derived_reason`` is one line, and it carries the rung.** D-F6's ladder is ordered
— reproduce the original experience, else build an equivalent interaction, else a deliberate
compact static fallback — and which rung a repair landed on is the single most useful thing a
human reviewing the lineage can be told. :func:`repair_reason` is the one place that sentence is
composed, so the tool that mints a repair and the test that reads one back cannot drift.
"""

from __future__ import annotations

#: A captured band that is mostly artificial scroll height (``sections/deadheight.py``). The
#: Ploy case: a scroll-jacked section whose height came from JavaScript that is not in the clone.
DEGRADED_REASON_DEAD_HEIGHT = "dead_height"

#: The codes this build can describe. NOT a closed vocabulary — see the module docstring.
DEGRADED_REASONS = (DEGRADED_REASON_DEAD_HEIGHT,)

#: One sentence per known code, in the terms the repair decision actually turns on. Written for
#: an agent that has to choose a ladder rung, not for a log.
_HEADLINES = {
    DEGRADED_REASON_DEAD_HEIGHT: (
        "the captured band is mostly artificial scroll height — a screenful of content "
        "followed by dead space, because the source page animated through it with JavaScript "
        "the clone does not carry. The repair must remove the empty height entirely."
    ),
}

#: The ladder, in D-F6's order. The number is what a repair records; the text is what it means.
REPAIR_RUNGS = {
    1: "reproduced the original experience with supported primitives",
    2: "built an equivalent interaction serving the same storytelling purpose",
    3: "a deliberate, compact static fallback with the artificial height removed entirely",
}

#: How long a repair's own note may be before it is cut. The column is free text and the row is
#: immutable, so this is a courtesy bound on one sentence, not a semantic limit.
REPAIR_NOTE_MAX_CHARS = 400


def degraded_headline(reason: str | None) -> str:
    """What ``reason`` means, for a human or an agent deciding what to do about it.

    An unknown code gets an honest sentence that quotes it rather than a guess about it: a row
    written by a producer this build has never met is a real possibility (the vocabulary is open),
    and inventing an explanation for it would be worse than admitting the gap.
    """
    if not reason:
        return "this clone is marked broken, with no reason recorded."
    known = _HEADLINES.get(reason)
    if known is not None:
        return known
    return (
        f"this clone is marked broken with reason {reason!r}, which this build has no "
        "description for. Look at the section's preview and its provenance before repairing it."
    )


def repair_reason(*, rung: int, trigger: str | None, note: str) -> str:
    """The one line a repair records in ``derived_reason``.

    Three facts, in the order they are asked: which rung of D-F6's ladder this repair reached,
    what was wrong with the original, and what the repair actually did. It is FROZEN at birth
    with the rest of the lineage, so it is composed once, here, rather than formatted at each
    call site.
    """
    if rung not in REPAIR_RUNGS:
        raise ValueError(
            f"repair rung must be one of {sorted(REPAIR_RUNGS)} (D-F6's ladder), not {rung!r}"
        )
    cleaned = " ".join((note or "").split())[:REPAIR_NOTE_MAX_CHARS]
    trigger_text = trigger or "unrecorded"
    return f"repair rung {rung} ({REPAIR_RUNGS[rung]}); trigger {trigger_text}; {cleaned}".strip()


__all__ = [
    "DEGRADED_REASONS",
    "DEGRADED_REASON_DEAD_HEIGHT",
    "REPAIR_NOTE_MAX_CHARS",
    "REPAIR_RUNGS",
    "degraded_headline",
    "repair_reason",
]
