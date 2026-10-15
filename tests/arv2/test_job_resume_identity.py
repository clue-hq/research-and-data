"""One function derives a research job's execution id (spec 2026-10-14 §3.2)."""

from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.job_resume import ResearchRestartRequired, research_execution_id


def test_restart_zero_is_the_id_every_job_already_has():
    job = uuid4()
    assert research_execution_id(job) == uuid5(NAMESPACE_URL, f"research-quality:{job}")
    assert research_execution_id(job, 0) == research_execution_id(job)


def test_each_restart_gets_its_own_stable_id():
    job = uuid4()
    ids = [research_execution_id(job, n) for n in range(3)]
    assert len(set(ids)) == 3
    assert research_execution_id(job, 2) == ids[2]


def test_a_reconciliation_unit_keeps_its_id_across_restarts():
    job = uuid4()
    legacy = uuid5(NAMESPACE_URL, f"research-quality:{job}:rev-3")
    assert research_execution_id(job, 0, "rev-3") == legacy
    assert research_execution_id(job, 4, "rev-3") == legacy


def test_a_negative_restart_count_is_refused():
    with pytest.raises(ValueError):
        research_execution_id(uuid4(), -1)


def test_the_restart_signal_names_its_reason():
    error = ResearchRestartRequired("instructions_changed")
    assert error.reason == "instructions_changed"


def test_a_job_scope_starts_at_restart_zero():
    assert JobScope.__dataclass_fields__["restart_count"].default == 0
