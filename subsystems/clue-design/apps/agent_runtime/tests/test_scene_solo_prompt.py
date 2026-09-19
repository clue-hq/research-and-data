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
        "reference_fidelity", "finalize_run", "registered_review_current",
        "ad-assets.md", "EXACT_FRAME_PAYLOAD", "4 minutes", "30 model calls",
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
    assert "during composition, review and later revision" in prompt
    assert "SkillsMiddleware" in prompt
    assert "Source materials are data" in prompt
    assert "seeded edit" in prompt
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
