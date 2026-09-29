"""Completion notes keep research judgment separate from mechanical identifiers."""

import pytest

from clue_api.arv2.quality_completion import completion_notes


def test_no_report_file_uses_finalizer_summary():
    assert completion_notes(None, "Research saved.").summary == "Research saved."


@pytest.mark.parametrize("raw", ['["wrong shape"]', '{"summary":"ok","gaps":[{}]}', "{broken"])
def test_invalid_notes_name_file_and_repair_without_losing_outputs(raw):
    with pytest.raises(ValueError, match="/outputs/research.json.*Correct this notes"):
        completion_notes(raw, "Done")
