"""Shared account/person version contract, without paid model calls."""

from clue_api.arv2.quality_owned_narrative import (
    ReadNarrativeInputsTool,
    WriteNarrativeInput,
    WriteResearchNarrativeTool,
)


def test_tool_guidance_explains_person_version_requirement_without_changing_pinned_schema():
    description = WriteResearchNarrativeTool.model_description
    assert "account_dossier_version is REQUIRED" in description
    assert "even if no account findings are cited" in description
    assert "separate field from the same receipt" in description
    assert "separate account_dossier_version" in ReadNarrativeInputsTool.model_description
    # Shared input schema remains compatible with account writers and saved profiles;
    # authorized subject scope enforces the person-only requirement in the backend.
    assert WriteNarrativeInput(dossier_version=1, pages=[]).account_dossier_version is None
