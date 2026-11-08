"""The account agent can nominate a person for every committee seat, and each seat reads and sorts.

The founder's committee model (2026-11-08) has an executive sponsor and an end user beside the
economic buyer, champion, technical evaluator and blocker. Before this, the trial nomination tools
had no label for either and the agent had to say "other".
"""

from typing import get_args

from clue_api.arv2.display.personas import persona_label, persona_rank
from clue_api.arv2.quality_committee_tool import NominateCommitteeInput, NominateWebCommitteeInput
from clue_api.arv2.quality_relationships import CommitteeAssessment


def test_every_nomination_shape_accepts_the_sponsor_and_end_user_seats() -> None:
    for model in (NominateCommitteeInput, NominateWebCommitteeInput, CommitteeAssessment):
        roles = set(get_args(model.model_fields["role"].annotation))
        assert {"executive_sponsor", "user"} <= roles, model.__name__


def test_the_sponsor_seat_has_words_and_sorts_after_the_economic_buyer() -> None:
    assert persona_label("executive_sponsor") == "Executive sponsor"
    assert persona_rank("economic_buyer") < persona_rank("executive_sponsor")
    assert persona_rank("executive_sponsor") < persona_rank("champion")
