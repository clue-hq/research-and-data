"""The committee persona vocabulary: the order it sorts in, and the words a person reads.

Two surfaces need this and must never disagree. :func:`~clue_api.arv2.display.gather
.committee_members` orders the committee a generated page speaks about; the read surface's
committee card and contacts table order the same people, and name their personas in the placeholder
it serves when the research recorded no reason for a member. A copy per side is how a card and a
page start listing one account's committee in two different orders.

It lives *here*, inside the display package, rather than in ``frontend_read.v1_shared`` where it
was born, because the dependency only runs one way: ``clue_api.arv2`` may not import
``clue_api.frontend_read`` (Global Constraint 7, machine-checked by
``tests/arv2/test_import_guard.py``). ``v1_shared`` re-exports both names, so every existing
importer is unaffected.
"""

from __future__ import annotations

__all__ = [
    "PERSONA_LABELS",
    "PERSONA_RANK",
    "persona_display",
    "persona_label",
    "persona_rank",
]

#: Committee ordering. A persona outside this tuple sorts last, then by name.
PERSONA_RANK: tuple[str, ...] = (
    "economic_buyer",
    "champion",
    "technical_evaluator",
    "user",
    "blocker",
)

#: The persona as a sentence names it. A persona outside the vocabulary has no label we can vouch
#: for, so it gets none — an invented one would put a word on a card that no claim supports.
PERSONA_LABELS: dict[str, str] = {
    "economic_buyer": "Economic buyer",
    "champion": "Champion",
    "technical_evaluator": "Technical evaluator",
    "user": "User",
    "blocker": "Blocker",
}


def persona_rank(persona: str | None) -> int:
    """Sort key for committee ordering; an unknown persona sorts after every known one."""
    try:
        return PERSONA_RANK.index(persona or "")
    except ValueError:
        return len(PERSONA_RANK)


def persona_label(persona: str | None) -> str | None:
    """``persona`` in the words a person reads, or ``None`` when it is outside the vocabulary."""
    return PERSONA_LABELS.get(persona or "")


def persona_display(persona: str | None) -> str | None:
    """``persona`` as a **screen** prints it — the vocabulary is never served raw (D4-b decision 5).

    Every ``persona`` slot on contract v1 carries display text, not the pipeline's enum value: a
    marketer reading the contacts table sees "Economic buyer", never ``economic_buyer``. The
    vocabulary value survives *inside* the read layer — the chip tone, the influence default and
    the committee ordering all still key on it — so this conversion happens at the wire, once.

    It differs from :func:`persona_label` on exactly one case, and the difference is the point.
    ``persona_label`` returns ``None`` for a value outside the vocabulary, because its caller (the
    committee card's "why they matter" placeholder) would rather say nothing than put a word it
    cannot vouch for into a sentence. Here the field is *required* and something must be served, so
    an unknown value is spelled as words — ``"weird_value"`` → ``"Weird value"`` — which is still
    the row's own value, only legible. Nothing is invented either way.

    Already-converted text is left alone (``"Economic buyer"`` in, ``"Economic buyer"`` out), which
    is what makes ``scripts/rewrite_display_persona_labels.py`` safe to run twice.
    """
    if persona is None or not persona.strip():
        return None
    value = persona.strip()
    return PERSONA_LABELS.get(value) or value.replace("_", " ").capitalize()
