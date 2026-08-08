"""P6.3 sandboxed runtime, generated props, and containment contracts."""

from __future__ import annotations

import base64
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as sa_text

from lumen_api.database import Repository, connect
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


RUNTIME_SOURCE = """
import React from "react";

type Props = {
  headline: string;
  count: number;
  showLogo: boolean;
  tone: "warm" | "direct";
};

export const meta = {
  name: "Runtime Card",
  description: "A typed runtime fixture."
};

export default function RuntimeCard({
  props: {
    headline = "Server first frame",
    count = 2,
    showLogo = true,
    tone = "warm"
  },
  theme
}: {
  props: Props;
  theme: { colors: { primary: string } };
  overrideVariables?: Record<string, string>;
}) {
  return (
    <section className={tone === "warm" ? "rounded-xl bg-primary p-6" : "rounded-xl bg-secondary p-6"}>
      <h2>{headline}</h2>
      <p>{count} items</p>
      {showLogo ? <strong>Logo</strong> : null}
      <small>{theme.colors.primary}</small>
    </section>
  );
}
"""


class RuntimeFrameParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.frames: list[dict[str, str | None]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "iframe":
            record = dict(attrs)
            if record.get("data-lumen-custom-component-runtime") == "true":
                self.frames.append(record)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "api.sqlite3"))


def create_account(client: TestClient, account_id: str = "acc_alpha") -> None:
    response = client.post(
        "/web/accounts",
        json={"account_id": account_id, "name": "Alpha"},
    )
    assert response.status_code == 200, response.text


def compile_runtime_artifact(client: TestClient) -> dict:
    source = client.put(
        "/web/accounts/acc_alpha/custom-components/runtime-card/source",
        json={
            "expected_version": 0,
            "files": {"runtime-card.tsx": RUNTIME_SOURCE},
        },
    )
    assert source.status_code == 200, source.text
    compiled = client.post(
        "/web/accounts/acc_alpha/custom-components/runtime-card/compile",
        json={"source_version": 1},
    )
    assert compiled.status_code == 200, compiled.text
    return compiled.json()["artifact"]


def create_document(client: TestClient) -> dict:
    web_doc = client.app.state.core.web_new_doc(
        "doc_runtime", "Runtime fixture", None
    )["web_doc"]
    ingested = client.app.state.core.web_ingest_html(
        web_doc,
        "home",
        "<section id='hero'><div id='stack'><p>Sibling stays visible</p></div></section>",
        None,
        None,
    )
    assert ingested.get("web_doc"), ingested
    repository = HybridRepository(connect(client.app.state.database_path))
    try:
        return repository.create_document(
            ingested["web_doc"],
            doc_kind="web",
            account_id="acc_alpha",
        )
    finally:
        repository.connection.close()


def container_id(document: dict) -> str:
    page = document["scene"]["pages"][0]
    return next(
        node_id
        for node_id, node in page["nodes"].items()
        if node["kind"] in {"container", "section"} and node_id != page["root"]
    )


def props(artifact: dict, **updates: object) -> dict:
    values = {
        "headline": "Editor headline",
        "count": 7,
        "showLogo": False,
        "tone": "direct",
    }
    values.update(updates)
    return {
        "kind": "custom_component",
        "slug": artifact["slug"],
        "artifact_id": artifact["artifact_id"],
        "props": values,
    }


def insert_component(client: TestClient, document: dict, artifact: dict) -> int:
    page = document["scene"]["pages"][0]
    inserted = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "base_version": 0,
            "intent": "insert_custom_component",
            "operations": [
                {
                    "kind": "insert_node",
                    "page_id": page["id"],
                    "parent": container_id(document),
                    "index": 1,
                    "nodes": [
                        {
                            "id": "cc_runtime",
                            "classes": "w-full min-h-[160px]",
                            **props(artifact),
                        }
                    ],
                    "root": "cc_runtime",
                }
            ],
        },
    )
    assert inserted.status_code == 200, inserted.text
    return inserted.json()["document"]["current_version"]


def nested_frame(html: str) -> dict[str, str | None]:
    parser = RuntimeFrameParser()
    parser.feed(html)
    assert len(parser.frames) == 1
    return parser.frames[0]


def decode_data_javascript(url: str) -> str:
    prefix = "data:text/javascript;base64,"
    assert url.startswith(prefix)
    return base64.b64decode(url[len(prefix) :]).decode("utf-8")


def module_script_src(srcdoc: str) -> str:
    marker = '<script type="module" src="'
    return srcdoc.split(marker, 1)[1].split('"', 1)[0]


def test_runtime_is_nested_opaque_networkless_and_hydrates_exact_pin(
    client: TestClient,
) -> None:
    create_account(client)
    artifact = compile_runtime_artifact(client)
    document = create_document(client)
    insert_component(client, document, artifact)

    response = client.get(
        f"/documents/{document['id']}/web/render"
        "?bridge=1&nonce=p6-runtime-123"
    )
    assert response.status_code == 200, response.text
    rendered = response.json()
    html = rendered["html"]
    frame = nested_frame(html)
    assert frame["sandbox"] == "allow-scripts"
    assert "allow-same-origin" not in str(frame["sandbox"])
    assert frame["referrerpolicy"] == "no-referrer"
    assert frame["data-runtime-contract-version"] == "1"
    assert frame["data-artifact-id"] == artifact["artifact_id"]
    assert frame["title"] == "Runtime Card component"
    assert frame["tabindex"] == "-1"
    assert 'data-custom-component-editor="true"' in html
    assert "pointer-events: none" in html

    srcdoc = str(frame["srcdoc"])
    assert "default-src 'none'" in srcdoc
    assert "connect-src 'none'" in srcdoc
    assert "frame-src 'none'" in srcdoc
    assert "worker-src 'none'" in srcdoc
    assert "form-action 'none'" in srcdoc
    assert "https://" not in srcdoc
    assert "http://" not in srcdoc
    assert "Server first frame" in srcdoc
    assert srcdoc.index("Server first frame") < srcdoc.index('type="module"')
    assert "@media (prefers-reduced-motion:reduce)" in srcdoc

    bootstrap = decode_data_javascript(module_script_src(srcdoc))
    assert f'"artifactId":"{artifact["artifact_id"]}"' in bootstrap
    assert '"headline":"Editor headline"' in bootstrap
    assert '"count":7' in bootstrap
    assert '"showLogo":false' in bootstrap
    assert '"tone":"direct"' in bootstrap
    assert "ReactDOM.hydrateRoot(root,tree" in bootstrap
    assert "RuntimeBoundary" in bootstrap
    assert "ResizeObserver" in bootstrap

    listing = client.get("/web/accounts/acc_alpha/custom-components")
    assert listing.status_code == 200, listing.text
    latest = listing.json()["components"][0]["latest_artifact"]
    assert latest["artifact_id"] == artifact["artifact_id"]

    bridge = html.split("<script>", 1)[-1]
    for trust_check in (
        "frame.contentWindow === event.source",
        'frame.getAttribute("data-runtime-nonce") === data.runtimeNonce',
        'frame.getAttribute("data-node-id-ref") === data.nodeId',
        'frame.getAttribute("data-artifact-id") === data.artifactId',
    ):
        assert trust_check in bridge


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda value: {**value, "unknown": "no"}, "unknown prop"),
        (lambda value: {**value, "count": "seven"}, "must be number"),
        (lambda value: {**value, "tone": "loud"}, "allowed values"),
        (
            lambda value: {key: item for key, item in value.items() if key != "headline"},
            "required prop",
        ),
    ],
)
def test_generated_prop_schema_rejects_invalid_whole_props_without_a_commit(
    client: TestClient,
    mutate,
    fragment: str,
) -> None:
    create_account(client)
    artifact = compile_runtime_artifact(client)
    document = create_document(client)
    version = insert_component(client, document, artifact)
    valid = props(artifact)["props"]

    rejected = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "base_version": version,
            "intent": "set_custom_component_props",
            "operations": [
                {
                    "kind": "set_node_props",
                    "page_id": "home",
                    "id": "cc_runtime",
                    "props": {
                        **props(artifact),
                        "props": mutate(valid),
                    },
                }
            ],
        },
    )
    assert rejected.status_code == 422, rejected.text
    detail = rejected.json()["detail"]
    assert detail["code"] == "custom_component.props_invalid"
    assert fragment in detail["message"]
    current = client.get(f"/documents/{document['id']}").json()
    assert current["current_version"] == version
    assert (
        current["scene"]["pages"][0]["nodes"]["cc_runtime"]["props"]
        == valid
    )


def test_all_generated_prop_types_persist_and_round_trip_undo_redo(
    client: TestClient,
) -> None:
    create_account(client)
    artifact = compile_runtime_artifact(client)
    document = create_document(client)
    version = insert_component(client, document, artifact)
    initial = props(artifact)["props"]
    updated = {
        "headline": "Persisted headline",
        "count": 12,
        "showLogo": True,
        "tone": "warm",
    }

    applied = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "base_version": version,
            "intent": "set_custom_component_props",
            "operations": [
                {
                    "kind": "set_node_props",
                    "page_id": "home",
                    "id": "cc_runtime",
                    "props": {
                        **props(artifact),
                        "props": updated,
                    },
                }
            ],
        },
    )
    assert applied.status_code == 200, applied.text
    persisted = client.get(f"/documents/{document['id']}").json()
    assert (
        persisted["scene"]["pages"][0]["nodes"]["cc_runtime"]["props"]
        == updated
    )

    rendered = client.get(f"/documents/{document['id']}/web/render")
    assert rendered.status_code == 200, rendered.text
    bootstrap = decode_data_javascript(
        module_script_src(str(nested_frame(rendered.json()["html"])["srcdoc"]))
    )
    assert '"headline":"Persisted headline"' in bootstrap
    assert '"count":12' in bootstrap
    assert '"showLogo":true' in bootstrap
    assert '"tone":"warm"' in bootstrap

    undone = client.post(f"/documents/{document['id']}/web/undo")
    assert undone.status_code == 200, undone.text
    after_undo = client.get(f"/documents/{document['id']}").json()
    assert (
        after_undo["scene"]["pages"][0]["nodes"]["cc_runtime"]["props"]
        == initial
    )

    redone = client.post(f"/documents/{document['id']}/web/redo")
    assert redone.status_code == 200, redone.text
    after_redo = client.get(f"/documents/{document['id']}").json()
    assert (
        after_redo["scene"]["pages"][0]["nodes"]["cc_runtime"]["props"]
        == updated
    )


def test_missing_runtime_host_and_artifact_are_contained_without_losing_siblings(
    client: TestClient, tmp_path: Path
) -> None:
    create_account(client)
    artifact = compile_runtime_artifact(client)
    document = create_document(client)
    insert_component(client, document, artifact)

    runtime_host = client.app.state.custom_component_runtime_host
    client.app.state.custom_component_runtime_host = tmp_path / "missing-host.js"
    host_missing = client.get(f"/documents/{document['id']}/web/render")
    assert host_missing.status_code == 200, host_missing.text
    html = host_missing.json()["html"]
    assert "Sibling stays visible" in html
    assert "Custom component unavailable" in html
    assert "trusted React runtime host could not be loaded" in html
    assert any(
        diagnostic["code"] == "LUMW0410"
        for diagnostic in host_missing.json()["diagnostics"]
    )

    client.app.state.custom_component_runtime_host = runtime_host
    repository = HybridRepository(connect(client.app.state.database_path))
    try:
        # D2.4B: the registry lives on Postgres; purge the row there to simulate the
        # missing-artifact case the renderer must contain. The citing compilation rows go
        # first: their artifact FK is ON DELETE SET NULL, and that SET NULL is itself an
        # UPDATE, which the compilation table's immutability trigger rejects. (No production
        # path deletes an artifact — the registry is INSERT-only — and the account CASCADE
        # removes compilations outright, so this ordering is a test-only concern.)
        for statement in (
            "DELETE FROM design_custom_component_compilation"
            " WHERE artifact_id = :i AND workspace_id = :w",
            "DELETE FROM design_custom_component_artifact"
            " WHERE artifact_id = :i AND workspace_id = :w",
        ):
            repository._bridge._run(
                lambda conn, sql=statement: conn.execute(
                    sa_text(sql),
                    {"i": artifact["artifact_id"], "w": repository.workspace_id},
                )
            )
    finally:
        repository.connection.close()
    artifact_missing = client.get(f"/documents/{document['id']}/web/render")
    assert artifact_missing.status_code == 200, artifact_missing.text
    assert "Sibling stays visible" in artifact_missing.json()["html"]
    assert "Custom component unavailable" in artifact_missing.json()["html"]
    assert artifact["artifact_id"] in artifact_missing.json()["html"]
    assert "is missing" in artifact_missing.json()["html"]
