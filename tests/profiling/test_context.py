"""M8 per-run context — reading the campaign coordinates out of ``AspectContext.params`` (pure)."""

from __future__ import annotations

from clue_research.claimstore import PUBLIC_ONLY
from clue_research.profiling import RunContext, params_for_run


def test_from_params_reads_all_coordinates() -> None:
    rc = RunContext.from_params(
        {"client_id": "acme", "icp_key": "us-mid", "icp_version": 3, "tenant_id": "acme"}
    )
    assert (rc.client_id, rc.icp_key, rc.icp_version, rc.tenant_id) == ("acme", "us-mid", 3, "acme")
    assert rc.has_icp


def test_tenant_defaults_to_client_when_absent() -> None:
    rc = RunContext.from_params({"client_id": "acme", "icp_key": "k", "icp_version": 1})
    assert rc.tenant_id == "acme"


def test_missing_icp_coordinate_is_not_has_icp() -> None:
    assert not RunContext.from_params({"client_id": "acme"}).has_icp
    assert not RunContext.from_params({}).has_icp


def test_icp_version_coerces_str_rejects_bool() -> None:
    assert RunContext.from_params({"icp_version": "7"}).icp_version == 7
    # bool is an int subclass — never a version.
    assert RunContext.from_params({"icp_version": True}).icp_version is None


def test_empty_params_is_all_none_and_public_scope() -> None:
    rc = RunContext.from_params({})
    assert (rc.client_id, rc.icp_key, rc.icp_version, rc.tenant_id) == (None, None, None, None)
    assert rc.tenant_scope() is PUBLIC_ONLY


def test_tenant_scope_for_tenant_is_not_public() -> None:
    rc = RunContext.from_params({"client_id": "acme"})
    scope = rc.tenant_scope()
    assert scope is not PUBLIC_ONLY  # a tenant view (public ∪ acme's private)


def test_params_for_run_omits_none_and_defaults_tenant() -> None:
    params = params_for_run(client_id="acme", icp_key="k", icp_version=2)
    assert params == {"client_id": "acme", "icp_key": "k", "icp_version": 2, "tenant_id": "acme"}
    sparse = params_for_run(client_id=None, icp_key=None, icp_version=None, tenant_id=None)
    assert sparse == {}


def test_params_round_trip_through_run_context() -> None:
    params = params_for_run(client_id="acme", icp_key="k", icp_version=4, tenant_id="t")
    rc = RunContext.from_params(params)
    assert (rc.client_id, rc.icp_key, rc.icp_version, rc.tenant_id) == ("acme", "k", 4, "t")
