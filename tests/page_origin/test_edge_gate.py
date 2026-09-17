from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from clue_page_origin import EdgeGate

from .conftest import HOST, FakePageReads, edge


def test_healthz_needs_no_secret(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_missing_or_wrong_secret_is_403_with_empty_body(
    client: TestClient, reads: FakePageReads
) -> None:
    reads.publish("annual-report", "<html></html>")
    for headers in (edge(secret=None), edge(secret="wrong")):
        response = client.get("/annual-report", headers=headers)
        assert response.status_code == 403
        assert response.content == b""


def test_forged_public_host_without_secret_is_403(client: TestClient) -> None:
    response = client.get("/annual-report", headers={"X-Clue-Public-Host": HOST})
    assert response.status_code == 403


def test_malformed_public_host_is_400(client: TestClient) -> None:
    assert client.get("/annual-report", headers=edge("not a host")).status_code == 400
    assert client.get("/annual-report", headers=edge("")).status_code == 400


def test_dev_mode_reads_the_host_header(dev_client: TestClient, reads: FakePageReads) -> None:
    reads.publish("annual-report", "<html>dev</html>")
    response = dev_client.get("/annual-report", headers={"Host": f"{HOST}:8040"})
    assert response.status_code == 200 and response.text == "<html>dev</html>"


def test_trust_and_secret_cannot_both_be_live() -> None:
    with pytest.raises(ValueError):
        EdgeGate(secret="x", trust_host_header=True)
    with pytest.raises(ValueError):
        EdgeGate(secret=None, trust_host_header=False)
