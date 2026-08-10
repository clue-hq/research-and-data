"""Lane D slice D3: the incremental ``finalize_turn.user_message`` extractor (charter §3.3(2)).

The parser half of the ratified §6-D2 contract, tested where it should be tested — as a pure
function over adversarial fragmentations, with no database, no model, and no socket. Every case the
charter's §5 streaming suite names about *decoding* lives here:

* a value split before, inside and after escapes, ``\\uXXXX`` sequences and multibyte Unicode;
* empty and malformed streamed arguments;
* Markdown constructs split across tokens;
* and the negative assertions — no surrounding JSON, no other argument of the same call, no other
  tool's arguments, and nothing at all from a provider's own reasoning text.

The exhaustive-boundary tests are the important ones: they re-feed the same document at **every**
split position, so a state machine that happens to work for one provider's chunk sizes cannot pass.
"""

from __future__ import annotations

import json

import pytest

from clue_api.chat.finalize_stream import (
    FINALIZE_TOOL_NAME,
    FinalizeTextDeltaExtractor,
    JsonStringFieldDecoder,
)


def _feed_in_chunks(document: str, size: int) -> tuple[str, JsonStringFieldDecoder]:
    decoder = JsonStringFieldDecoder()
    out: list[str] = []
    for index in range(0, len(document), size):
        out.append(decoder.feed(document[index : index + size]))
    return "".join(out), decoder


def _feed_split_at(document: str, position: int) -> tuple[str, JsonStringFieldDecoder]:
    decoder = JsonStringFieldDecoder()
    first = decoder.feed(document[:position])
    second = decoder.feed(document[position:])
    return first + second, decoder


# --- the value, however it is cut ---------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "hello",
        "",
        'a "quoted" word',
        "back\\slash",
        "line one\nline two\ttabbed",
        "café — naïve — 日本語",
        "emoji 😀 and 👩‍💻 zwj",
        "control  bell",
        "# Heading\n\n- bullet **bold** `code`\n\n```py\nprint('x')\n```\n",
        "50% of the time it's a \\ or a \" or a  ",
    ],
)
def test_the_value_reconstructs_byte_identically_at_every_split_position(value: str) -> None:
    """The core promise: ``join(deltas)`` equals the value, whatever the chunk boundaries are.

    Every split position of the whole document, not a sampled few — including splits that land in
    the middle of ``\\uXXXX``, between the halves of a surrogate pair, and inside the key name.
    """

    document = json.dumps({"user_message": value})
    for position in range(len(document) + 1):
        emitted, decoder = _feed_split_at(document, position)
        assert emitted == value, f"split at {position} of {document!r}"
        assert decoder.text == value
        assert decoder.complete is True
        assert decoder.failed is False


@pytest.mark.parametrize("size", [1, 2, 3, 5, 7, 13])
def test_the_value_reconstructs_under_uniform_chunking(size: int) -> None:
    value = 'Résumé: 😀 **bold** "quoted" \\ backslash\nnewline'
    document = json.dumps({"user_message": value})
    emitted, decoder = _feed_in_chunks(document, size)
    assert emitted == value
    assert decoder.complete is True


def test_a_split_between_the_halves_of_a_surrogate_pair_never_emits_half_a_character() -> None:
    """A high surrogate is not a character. It is held until its partner arrives, so a consumer
    never receives a code point that cannot even be UTF-8 encoded."""

    # ``ensure_ascii`` forces the astral character into an explicit surrogate pair.
    document = json.dumps({"user_message": "x😀y"}, ensure_ascii=True)
    assert "\\ud83d\\ude00" in document.lower()
    split = document.lower().index("\\ud83d") + 6  # exactly between the two escapes
    decoder = JsonStringFieldDecoder()
    first = decoder.feed(document[:split])
    assert first == "x"  # the high surrogate is pending, not emitted
    second = decoder.feed(document[split:])
    assert first + second == "x😀y"
    assert decoder.failed is False


def test_a_split_inside_a_unicode_escape_holds_until_the_escape_completes() -> None:
    document = json.dumps({"user_message": "aéb"}, ensure_ascii=True)
    for position in range(len(document) + 1):
        emitted, decoder = _feed_split_at(document, position)
        assert emitted == "aéb"
        assert "\\u" not in emitted
        assert decoder.complete is True


def test_an_empty_value_still_starts_and_completes() -> None:
    """``{"user_message": ""}`` must be representable: a started, completed, zero-delta part.

    Without ``started`` the emitter could not tell "the model produced an empty message" from "the
    model never produced a message", and the frontend's ``text.min(1)`` trap would be re-created on
    the backend.
    """

    decoder = JsonStringFieldDecoder()
    emitted = decoder.feed('{"user_message": ""}')
    assert emitted == ""
    assert decoder.started is True
    assert decoder.complete is True


# --- nothing but the value ----------------------------------------------------------------------


def test_no_surrounding_json_or_sibling_argument_is_ever_emitted() -> None:
    """The §3.3 negative assertion: only the one field's characters, never the document."""

    document = json.dumps(
        {
            "status": "completed",
            "failure_code": None,
            "user_message": "the answer",
            "domain_refs": [{"object_type": "project", "object_id": "prj_1"}],
        }
    )
    for size in (1, 4, 11):
        emitted, decoder = _feed_in_chunks(document, size)
        assert emitted == "the answer"
        assert decoder.text == "the answer"
        for leaked in ("status", "completed", "domain_refs", "prj_1", "{", "}", '"'):
            assert leaked not in emitted


def test_a_nested_user_message_key_is_not_the_field() -> None:
    """Only the *top level* of the call's own argument object arms the value decoder."""

    document = json.dumps(
        {
            "domain_refs": [{"user_message": "not this one"}],
            "nested": {"user_message": "nor this"},
            "user_message": "this one",
        }
    )
    emitted, decoder = _feed_in_chunks(document, 3)
    assert emitted == "this one"
    assert "not this one" not in decoder.text
    assert "nor this" not in decoder.text


def test_another_tool_call_in_the_same_round_emits_nothing() -> None:
    extractor = FinalizeTextDeltaExtractor()
    other = extractor.feed_tool_call_chunk(
        index=0,
        name="draft_account_research_directive",
        args='{"user_message": "a tool argument, not prose"}',
    )
    assert other == ""
    ours = extractor.feed_tool_call_chunk(
        index=1, name=FINALIZE_TOOL_NAME, args='{"user_message": "prose"}'
    )
    assert ours == "prose"
    assert extractor.text == "prose"


def test_an_unnamed_call_is_never_assumed_to_be_the_finalize_call() -> None:
    """Guessing that an unnamed stream is ours is exactly how surrounding JSON leaks."""

    extractor = FinalizeTextDeltaExtractor()
    assert extractor.feed_tool_call_chunk(index=0, name=None, args='{"user_mes') == ""
    # Even if the name shows up later, the fragments already dropped make the scanner unsafe.
    assert (
        extractor.feed_tool_call_chunk(index=0, name=FINALIZE_TOOL_NAME, args='sage": "x"}') == ""
    )
    assert extractor.text == ""


# --- malformed input fails closed ---------------------------------------------------------------


@pytest.mark.parametrize(
    "document",
    [
        '{"user_message": "bad \\q escape"}',
        '{"user_message": "lone high \\ud83d surrogate"}',
        '{"user_message": "lone low \\udc00 surrogate"}',
        '{"user_message": "not hex \\uZZZZ"}',
    ],
)
def test_malformed_arguments_fail_closed_and_invent_nothing(document: str) -> None:
    decoder = JsonStringFieldDecoder()
    decoder.feed(document)
    assert decoder.failed is True
    assert decoder.complete is False
    # Whatever decoded before the fault stands; nothing after it is guessed at.
    assert "\\u" not in decoder.text
    assert "\ud83d" not in decoder.text


def test_a_raw_control_character_inside_the_string_fails_closed() -> None:
    decoder = JsonStringFieldDecoder()
    decoder.feed('{"user_message": "a\nb"}')  # a *raw* newline is invalid JSON string content
    assert decoder.failed is True


def test_a_non_string_value_streams_nothing_and_does_not_fail() -> None:
    """``{"user_message": null}`` is a well-formed document with no prose in it."""

    decoder = JsonStringFieldDecoder()
    emitted = decoder.feed('{"user_message": null, "status": "failed"}')
    assert emitted == ""
    assert decoder.failed is False
    assert decoder.started is False


def test_truncated_arguments_leave_the_decoder_open_rather_than_completing() -> None:
    """A stream that dies mid-value is *incomplete*, never silently "finished"."""

    decoder = JsonStringFieldDecoder()
    emitted = decoder.feed('{"user_message": "half a sen')
    assert emitted == "half a sen"
    assert decoder.complete is False
    assert decoder.failed is False


# --- byte-level fragmentation -------------------------------------------------------------------


def test_a_multibyte_code_point_split_across_byte_fragments_is_reassembled() -> None:
    """The ``feed_bytes`` path: a UTF-8 code point cut in half by the transport.

    The JSON scanner never sees the broken halves — an incremental UTF-8 decoder reassembles them
    first — so "split multibyte UTF-8" costs the parser nothing.
    """

    value = "日本語 😀 café"
    raw = json.dumps({"user_message": value}, ensure_ascii=False).encode()
    for position in range(len(raw) + 1):
        extractor = FinalizeTextDeltaExtractor()
        first = extractor.feed_tool_call_chunk(
            index=0, name=FINALIZE_TOOL_NAME, args=raw[:position]
        )
        second = extractor.feed_tool_call_chunk(index=0, name=None, args=raw[position:])
        assert first + second == value, f"byte split at {position}"
        assert extractor.text.encode() == value.encode()


def test_markdown_split_across_tokens_reconstructs_exactly() -> None:
    """§5's "Markdown constructs split across tokens": the backend's job is byte fidelity.

    Rendering is the frontend's problem; what this proves is that no fence, no list marker and no
    inline construct is corrupted by the split, so the renderer receives what the model wrote.
    """

    value = (
        "Here is the plan:\n\n"
        "1. **Draft** the directive\n"
        "2. Review `budget_cap_cents`\n\n"
        '```json\n{"accounts": 2}\n```\n\n'
        "> and a quote\n"
    )
    document = json.dumps({"user_message": value})
    # Token-shaped chunking (a few characters at a time), then character-at-a-time.
    for size in (1, 2, 6, 17):
        emitted, decoder = _feed_in_chunks(document, size)
        assert emitted == value
        assert decoder.complete is True
