"""M8 per-run context — reading the campaign coordinates out of ``AspectContext.params`` (pure)."""

from __future__ import annotations

from clue_research.claimstore import PUBLIC_ONLY
from clue_research.profiling import RunContext, params_for_run


def test_from_params_reads_all_coordinates() -> None:
    rc = RunContext.from_params({"workspace_id": "acme", "icp_key": "us-mid", "icp_version": 3})
    assert (rc.workspace_id, rc.icp_key, rc.icp_version) == ("acme", "us-mid", 3)
    assert rc.has_icp


def test_missing_icp_coordinate_is_not_has_icp() -> None:
    assert not RunContext.from_params({"workspace_id": "acme"}).has_icp
    assert not RunContext.from_params({}).has_icp


def test_icp_version_coerces_str_rejects_bool() -> None:
    assert RunContext.from_params({"icp_version": "7"}).icp_version == 7
    # bool is an int subclass — never a version.
    assert RunContext.from_params({"icp_version": True}).icp_version is None


def test_empty_params_is_all_none_and_public_scope() -> None:
    rc = RunContext.from_params({})
    assert (rc.workspace_id, rc.icp_key, rc.icp_version) == (None, None, None)
    assert rc.workspace_scope() is PUBLIC_ONLY


def test_workspace_scope_for_workspace_is_not_public() -> None:
    rc = RunContext.from_params({"workspace_id": "acme"})
    scope = rc.workspace_scope()
    assert scope is not PUBLIC_ONLY  # a workspace view (public ∪ acme's private)


def test_params_for_run_omits_none() -> None:
    params = params_for_run(workspace_id="acme", icp_key="k", icp_version=2)
    assert params == {"workspace_id": "acme", "icp_key": "k", "icp_version": 2}
    sparse = params_for_run(workspace_id=None, icp_key=None, icp_version=None)
    assert sparse == {}


def test_params_round_trip_through_run_context() -> None:
    params = params_for_run(workspace_id="acme", icp_key="k", icp_version=4)
    rc = RunContext.from_params(params)
    assert (rc.workspace_id, rc.icp_key, rc.icp_version) == ("acme", "k", 4)
