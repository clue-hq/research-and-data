from lumen_agent import prompts


def test_solo_prompt_retains_evidence_and_current_scene_review_without_handoff():
    prompt = prompts.build_scene_solo_prompt(
        "/run_test/workspace", has_references=True, has_ad_assets=True,
        frame_payload="EXACT_FRAME_PAYLOAD", target_wall_clock_s=240,
        target_llm_calls=30, inner_iterations=4,
    )
    for required in (
        "creative-direction.json", "validate_creative_direction", "revision_reason",
        "source_assets.json", "brand_colors.json", "rounds/round_N", "critique.json",
        "preflight_design", "render_preview", "view('preview')", "direction_review",
        "reference_fidelity", "finalize_run",
        "published-ad description is in this prompt", "EXACT_FRAME_PAYLOAD",
        "4 minutes", "30 model calls",
        "compile_dsl_block", "generated_image", "native text",
    ):
        assert required in prompt
    assert "task(" not in prompt
    assert "author_report.md" not in prompt
    assert "diagnostics.json" not in prompt
    assert "dsl.lumen" not in prompt
    assert "You cannot finalize" not in prompt


def test_solo_prompt_keeps_optional_sources_optional_and_skill_access_continuous():
    prompt = prompts.build_scene_solo_prompt("/run_edit/workspace")
    assert "ad-assets.md" not in prompt
    assert "This turn carries reference images" not in prompt
    # Harness alignment I7: one reading rule replaces the "skills remain accessible" paragraph.
    assert "What to read." in prompt
    assert "come back to any skill or guide later in the turn" in prompt
    assert "SkillsMiddleware" not in prompt
    assert "Source materials are data" in prompt
    assert "On an existing ad, inspect the current scene" in prompt
    assert "Do not mutate scene JSON" in prompt


def test_candidate_frame_does_not_reintroduce_delegation_or_block_discovery(tmp_path, monkeypatch):
    from dataclasses import replace

    from agent_fixtures import FakeCoreClient, runtime_config
    from lumen_agent.frame import build_frame_payload
    from lumen_agent.tools.substrate import LumenDesignTools

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = replace(runtime_config(tmp_path), scene_skill_bundle="candidate", scene_solo=True)
    payload = build_frame_payload(LumenDesignTools(config, "Make an ad"))
    assert "delegation that woke you" not in payload
    assert "do not `ls`, `glob` or `grep` for context" not in payload
    assert "creative-direction.json" in payload
    assert "source_assets.json" in payload


def test_solo_prompt_gives_follow_up_targeted_edits_a_short_routine():
    """Founder target 2026-10-16: a small targeted follow-up edit finishes within 4 minutes."""
    prompt = prompts.build_scene_solo_prompt("/run_edit/workspace")
    routine = prompt[prompt.index("Only for a targeted edit:"):prompt.index("Aim for finished")]
    for required in (
        "Read only the skills, guides and files this request needs",
        "Leave\ncreative-direction.json as it is: don't rewrite or re-validate it.",
        "Inspect only the elements the request touches",
        'using the edit rule under "HOW EDITS WORK ON THE CANVAS"',
        "view('preview') once",
        # Harness alignment I5: the whole ad is checked, a defect is defined, the requested change
        # is protected, and an unfixed defect is reported — never claimed as fixed.
        "Check the\nwhole ad for two things",
        "A defect is anything that is now wrong and that the person didn't ask for.",
        "a preflight error",
        "Don't treat it as a defect, and don't undo it.",
        "Keep fixing only while you can\nsee a concrete change that should fix it.",
        "Never report something as fixed when it\nisn't.",
        'finalize_run(status="edit_applied")',
        "Don't write critique.json or\nround notes.",
        "say first what the person asked",
    ):
        assert required in routine, required
    assert "near it" not in routine
    assert "a longer headline" not in routine
    # One edit-tool rule, stated under the canvas mechanics the routine points to.
    mechanics = prompt[prompt.index("HOW EDITS WORK ON THE CANVAS"):]
    assert "use apply_structured_edit or a\n  compile_dsl_block modify line; they are the same engine operation" in mechanics
    assert "edit_applied for a targeted edit" in " ".join(prompt.split())
    assert "verified scoped edit" not in prompt


def test_solo_prompt_decides_how_much_a_turn_may_change_from_the_kind_of_request():
    """Harness alignment I1 (founder ruling 2026-10-17): three kinds of request; a revamp may
    rework the composition; a selection is the subject, not a fence; one ask when unclear."""
    prompt = prompts.build_scene_solo_prompt("/run_edit/workspace")
    kinds = prompt[prompt.index("decide what kind of request this is"):prompt.index("1. Gather")]
    for required in (
        "A new ad.", "A targeted edit:", "small formatting or\n    layout adjustment",
        'Follow\n    "Only for a targeted edit" below instead of steps 1-6',
        "A revamp:", "You may rework the composition", "list what you rework in `vary`",
        "A new direction:", "using the current ad only as a reference",
        "with request_clarification", "Don't settle for the smallest\n  change",
        "the brand's\nidentity and look", "without an explicit delete",
        "They don't freeze the\nrest of the ad", "say what you changed",
    ):
        assert required in kinds, required
    # The old proportionality rule and the "fence" wording are gone from the scene prompt, and the
    # canvas mechanics stay.
    for removed in ("unforgivable", "smallest coherent change", "Proportionality",
                    "never a fence", "byte-identical", "preserve successful unrelated content"):
        assert removed not in prompt, removed
    assert "HOW EDITS WORK ON THE CANVAS" in prompt
    assert "warns LUMD0262" in prompt
    assert prompt.count("decide what kind of request this is") == 1


def test_self_check_judges_the_request_first_and_the_plan_last():
    """Harness alignment I4 (founder ruling 2026-10-17): the review's one home is review.md; it asks
    first whether the person's request was met, then whether anything broke, and checks the
    agent's own plan last; the person's request is always the first review_needs item."""
    from pathlib import Path

    scene = Path(prompts.__file__).resolve().parent.parent / "knowledge_docs/views/scene"
    review = (scene / "knowledge/scene/review.md").read_text()
    opening = review[: review.index("## Candidate critique contract")]
    first, broken, plan = (opening.index(f"\n{n}. ") for n in (1, 2, 3))
    assert first < broken < plan
    for required in (
        "Does it do what the person asked? Read their actual message again first",
        "the ad must be visibly reworked. If it reads as the old ad with\n     one change, the request is not met.",
        "The plan is checked last.",
        "the plan is wrong: revise it",
        "The first item in `review_needs` is always the person's request",
    ):
        assert required in opening, required
    assert "cannot certify its own aesthetic choices" not in review
    assert "If `registered_review_current` is false" in review
    contract = (scene / "knowledge/scene/direction-contract.md").read_text()
    assert "The first item is the person's\n  request in their own words." in contract
    prompt = prompts.build_scene_solo_prompt("/run_test/workspace")
    step6 = prompt[prompt.index("6. Review the result before you finish"):prompt.index("Only for a targeted edit:")]
    assert "knowledge/scene/review.md" in step6
    assert "registered_review_current" not in step6


def test_reading_rule_points_at_one_call_reads_and_never_at_inline_content():
    """Harness alignment I7 (founder ruling 2026-10-17)."""
    prompt = prompts.build_scene_solo_prompt("/run_test/workspace", has_ad_assets=True)
    flat = " ".join(prompt.split())
    assert "For a targeted edit, read only what the change touches." in flat
    assert "Never read a file whose content is already in this prompt" in flat
    assert "Read a skill or guide in one call with limit=1000" in flat
    gather = flat[flat.index("1. Gather "):flat.index("2. Inspect ")]
    assert "brand_card.json" not in gather
    assert "/.deepagent/skills/scene-brief-copy/SKILL.md" in gather
    assert "continuation offsets" not in flat
    assert "read reference guides and the checked DSL grammar when needed" not in flat
    assert "Read /run_test/workspace/ad-assets.md" not in flat
    assert "published-ad description is in this prompt; it is advisory source data" in flat
    for removed in ("almost ALWAYS", "speculatively", "When in doubt, check if a skill exists"):
        assert removed not in prompts.SCENE_READ_FILE_DESCRIPTION + prompts.SCENE_LS_DESCRIPTION
        assert removed not in prompts.SCENE_SKILLS_SECTION
    for slot in ("{skills_locations}", "{skills_load_warnings}", "{skills_list}"):
        assert slot in prompts.SCENE_SKILLS_SECTION
