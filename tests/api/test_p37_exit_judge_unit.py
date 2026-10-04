"""Adversarial-review fix — the LIVE exit judge parses real gateway completions.

The gateway builds Responses-API models (``use_responses_api=True,
output_version="responses/v1"``), whose ``AIMessage.content`` is a LIST of content
blocks, never a plain string. The first judge handled only ``str``/``dict`` and fell
through to ``str(list)`` — a Python repr that never parses — so every verdict became the
fail-safe CONTINUE and the whole exit bridge was inert in production, invisibly. These
tests drive ``build_design_leg_exit_judge`` through fake providers returning the REAL
LangChain message shapes and pin that a verdict actually comes back.

Offline: no DB, no model.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from clue_api.agent_turn_fleet_wiring import build_design_leg_exit_judge
from clue_design.exit_judgment import ExitJudgment
from tests.db.conftest import run_async

_VERDICT = (
    '{"close_this_session": true, "current_artifact_accepted": true, "reasoning": "accepted"}'
)


class _FakeModel:
    def __init__(self, completion: Any) -> None:
        self._completion = completion
        self.prompts: list[Any] = []
        self.configs: list[Any] = []

    async def ainvoke(self, prompt: Any, **kwargs: Any) -> Any:
        self.prompts.append(prompt)
        self.configs.append(kwargs)
        return self._completion


class _FakeModels:
    def __init__(self, model: _FakeModel) -> None:
        self._model = model
        self.build_calls: list[dict[str, Any]] = []

    def build(self, **kwargs: Any) -> _FakeModel:
        self.build_calls.append(kwargs)
        return self._model


class _FakeProfiles:
    """resolve(role) -> .profile.model with the ModelPolicy fields the builder reads."""

    class _Policy:
        model_id = "openai/gpt-5.6-terra"
        timeout_s = 120.0
        max_retries = 2
        max_output_tokens = 32768
        temperature = 1.0

    class _Profile:
        model = None  # replaced below

    class _Resolved:
        profile = None

    def resolve(self, role: Any) -> Any:
        profile = self._Profile()
        profile.model = self._Policy()
        resolved = self._Resolved()
        resolved.profile = profile
        return resolved


def _judge_with(completion: Any) -> tuple[Any, _FakeModel]:
    model = _FakeModel(completion)
    judge = build_design_leg_exit_judge(models=_FakeModels(model), profiles=_FakeProfiles())
    return judge, model


_LOCKED = ExitJudgment(
    close_this_session=True, current_artifact_accepted=True, reasoning="accepted"
)


def _run(judge: Any) -> ExitJudgment | None:
    return run_async(
        judge(
            brief="An artboard.",
            history=(("user", "Bolder."),),
            message="Lock it in.",
            artifact='design "An artboard" (scene ad)',
            tags=('account "Apollo Clinics"',),
        )
    )


def test_a_responses_api_block_list_completion_yields_a_verdict() -> None:
    """The production shape: content is a LIST of text blocks (responses/v1)."""

    judge, model = _judge_with(
        AIMessage(content=[{"type": "text", "text": _VERDICT, "annotations": []}])
    )
    assert _run(judge) == _LOCKED
    assert "prompt_version" in model.prompts[0]  # the P3.6 versioned prompt went out
    # v2: the judge saw the artifact line and the tags the runner resolved.
    assert 'design "An artboard" (scene ad)' in model.prompts[0]
    assert '- account "Apollo Clinics"' in model.prompts[0]


def test_a_multi_block_completion_concatenates_its_text_blocks() -> None:
    judge, _ = _judge_with(
        AIMessage(
            content=[
                {
                    "type": "text",
                    "text": '{"close_this_session": true, "hand_message_to_strategy_agent": true,',
                },
                {"type": "reasoning", "summary": "thinking..."},
                {"type": "text", "text": ' "reasoning": "a strategy ask"}'},
            ]
        )
    )
    assert _run(judge) == ExitJudgment(
        close_this_session=True, hand_message_to_strategy_agent=True, reasoning="a strategy ask"
    )


def test_a_plain_string_completion_still_parses() -> None:
    judge, _ = _judge_with(AIMessage(content=_VERDICT))
    assert _run(judge) == _LOCKED


def test_garbage_and_provider_errors_stay_fail_safe() -> None:
    judge, _ = _judge_with(AIMessage(content=[{"type": "text", "text": "no json here"}]))
    assert _run(judge) is None

    class _ExplodingModels:
        def build(self, **kwargs: Any) -> Any:
            raise RuntimeError("gateway down")

    exploding = build_design_leg_exit_judge(models=_ExplodingModels(), profiles=_FakeProfiles())
    assert _run(exploding) is None


def test_with_langfuse_the_judge_is_an_evaluator_holding_its_generation() -> None:
    from tests._langfuse import finished_spans, langfuse_installed

    with langfuse_installed() as (exporter, _provider):
        judge, model = _judge_with(AIMessage(content=_VERDICT))
        verdict = _run(judge)
        spans = finished_spans(exporter)
    assert verdict is not None
    evaluator = next(s for s in spans if s.name == "design-leg.exit_judge")
    attrs = dict(evaluator.attributes or {})
    assert attrs["langfuse.observation.type"] == "evaluator"
    assert attrs["langfuse.trace.name"] == "design-leg.exit_judge"
    assert "close_this_session" in attrs["langfuse.observation.output"]
    # The handler was attached to the direct model call so its generation nests here.
    assert model.configs and "callbacks" in (model.configs[0].get("config") or {})


def test_without_langfuse_no_config_is_passed_to_the_model() -> None:
    judge, model = _judge_with(AIMessage(content=_VERDICT))
    assert _run(judge) is not None
    assert model.configs == [{}]


def test_v3_the_judge_is_shown_the_legs_numbered_artifacts() -> None:
    """A multi-document leg passes ``artifacts=``; the whole numbered list must reach the
    model and the tag must carry its number, or the judge cannot answer an address."""

    judge, model = _judge_with(AIMessage(content=_VERDICT))
    verdict = run_async(
        judge(
            brief="Three launch ads.",
            history=(),
            message="the two hospital ones need a softer palette",
            artifacts=(
                '1. "Apollo ad" (scene ad) [account: Apollo Clinics]',
                '2. "Mercy ad" (scene ad) [account: Mercy Health]',
                '3. "Premier ad" (scene ad) [account: Premier Gastro]',
            ),
            tags=('design "Mercy ad" (scene ad) (artifact 2)',),
        )
    )
    assert verdict is not None
    prompt = model.prompts[0]
    assert '<<<ARTIFACTS\n1. "Apollo ad" (scene ad) [account: Apollo Clinics]' in prompt
    assert '3. "Premier ad" (scene ad) [account: Premier Gastro]\nARTIFACTS>>>' in prompt
    assert '- design "Mercy ad" (scene ad) (artifact 2)' in prompt
    assert "addressed_artifacts" in prompt and "clarifying_question" in prompt


def test_v4_the_judge_is_told_an_asked_artifact_is_waiting_for_an_answer() -> None:
    """Spec 2026-09-20 §2.5: a bare answer ("the 40% stat") names no artifact, so without
    this instruction the judge asks which one the user already answered for."""

    judge, model = _judge_with(AIMessage(content=_VERDICT))
    verdict = run_async(
        judge(
            brief="Three launch ads.",
            history=(),
            message="the 40% stat",
            artifacts=(
                '1. "Apollo ad" (scene ad)',
                '2. "Mercy ad" (scene ad) [asked: "Which proof point should lead the ad?"]',
            ),
        )
    )
    assert verdict is not None
    prompt = model.prompts[0]
    assert (
        "- An artifact marked [asked: …] is waiting for an answer; a message that answers one of\n"
        "  those questions is work on THAT artifact, even when it names nothing.\n"
    ) in prompt
    assert '[asked: "Which proof point should lead the ad?"]' in prompt
    assert prompt.rstrip().endswith("prompt_version: v4")


def test_the_judges_output_budget_leaves_room_for_a_question() -> None:
    """v3's answer can carry a clarifying question on top of the reasoning; a truncated
    verdict is an unparseable one, which costs a whole fail-safe turn."""

    model = _FakeModel(AIMessage(content=_VERDICT))
    models = _FakeModels(model)
    judge = build_design_leg_exit_judge(models=models, profiles=_FakeProfiles())
    assert _run(judge) == _LOCKED
    assert models.build_calls[0]["max_output_tokens"] == 600


def test_the_judges_model_call_has_a_hard_deadline() -> None:
    """Production 2026-10-04: a non-streamed judge call to a stalled provider hung for 13
    minutes (its per-read timeout never fired). A per-model deadline lets the fallback chain
    take over, and the judge's own fail-safe still answers if every model stalls."""

    model = _FakeModel(AIMessage(content=_VERDICT))
    models = _FakeModels(model)
    judge = build_design_leg_exit_judge(models=models, profiles=_FakeProfiles())
    assert _run(judge) == _LOCKED
    deadline = models.build_calls[0]["call_deadline_s"]
    assert 0 < deadline <= 60
