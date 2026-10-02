from types import SimpleNamespace

from clue_api.chat.turn_stream import reasoning_deltas_from_chunk


def test_canonical_block_is_not_duplicated_by_provider_aliases() -> None:
    message = SimpleNamespace(
        content=[{"type": "reasoning", "reasoning": "again again"}],
        additional_kwargs={"reasoning_content": "again again"},
    )
    assert reasoning_deltas_from_chunk(message) == ("again again",)


def test_responses_and_standard_content_blocks() -> None:
    assert reasoning_deltas_from_chunk(
        SimpleNamespace(
            content=[
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "summary"}]}
            ]
        )
    ) == ("summary",)
    assert reasoning_deltas_from_chunk(
        SimpleNamespace(
            content="answer", content_blocks=[{"type": "reasoning", "reasoning": "trace"}]
        )
    ) == ("trace",)


def test_only_displayable_details_not_encrypted_or_answer_or_tools() -> None:
    assert reasoning_deltas_from_chunk(
        SimpleNamespace(
            content="answer",
            additional_kwargs={
                "reasoning_details": [
                    {"type": "reasoning.encrypted", "data": "secret", "text": "not displayable"},
                    {"type": "reasoning.text", "text": "trace"},
                    {"type": "reasoning.summary", "summary": "summary"},
                ]
            },
            tool_calls=[{"args": {"user_message": "answer"}}],
        )
    ) == ("trace", "summary")
    assert reasoning_deltas_from_chunk(SimpleNamespace(content="answer")) == ()


def test_scalar_alias_wins_over_details_and_malformed_details_are_ignored() -> None:
    assert reasoning_deltas_from_chunk(
        SimpleNamespace(
            additional_kwargs={
                "reasoning_content": "same",
                "reasoning_details": [{"type": "reasoning.text", "text": "same"}],
            }
        )
    ) == ("same",)
    assert (
        reasoning_deltas_from_chunk(
            SimpleNamespace(
                content=[
                    {"type": "reasoning", "summary": 42},
                ],
                additional_kwargs={
                    "reasoning_details": [None, {"type": "reasoning.text", "text": {}}]
                },
            )
        )
        == ()
    )
