import assert from "node:assert/strict";
import test from "node:test";
import { DesignArtifactListItemSchema } from "../model/artifact";
import {
  DesignArtifactError,
  fixtureDesignArtifactRepository,
  httpDesignArtifactRepository,
} from "./artifact.repository";

test("the fixture adapter serves its artifact and refuses unknown ids typed", async () => {
  const repository = fixtureDesignArtifactRepository();
  const artifact = await repository.get(
    "10m-landing-page-campaign",
    "doc_web_fixture",
  );
  assert.equal(artifact.kind, "web");
  assert.equal(artifact.documentId, artifact.id);
  await assert.rejects(
    repository.get("10m-landing-page-campaign", "doc_missing"),
    (error: unknown) =>
      error instanceof DesignArtifactError &&
      error.code === "ARTIFACT_NOT_FOUND" &&
      error.status === 404,
  );
});

test("the fixture adapter lists only the asked-for project's artifacts", async () => {
  const repository = fixtureDesignArtifactRepository();
  const artifacts = await repository.list("10m-landing-page-campaign");
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].id, "doc_web_fixture");
  assert.equal(artifacts[0].originThreadId, "thread_fixture");
  assert.equal(artifacts[0].updatedAt, "2026-08-16T12:30:00+00:00");
  // A project with no design legs has no artifacts — an empty list, not a refusal.
  assert.deepEqual(await repository.list("other-project"), []);
});

test("the fixture adapter serves the feed newest-updated first", async () => {
  const item = (id: string, updatedAt: string) =>
    DesignArtifactListItemSchema.parse({
      id,
      projectId: "prj-1",
      documentId: id,
      kind: "web",
      title: id,
      currentVersionId: "1",
      status: "draft",
      createdAt: "2026-08-10T09:00:00+00:00",
      updatedAt,
      originThreadId: "thread-1",
    });
  // The offsets matter: ordering is by instant, not by how the string reads.
  const repository = fixtureDesignArtifactRepository([
    item("older", "2026-08-14T12:00:00+05:30"), // 06:30Z
    item("newest", "2026-08-18T04:00:00+05:30"), // Aug 17, 22:30Z
    item("middle", "2026-08-14T09:00:00+00:00"),
  ]);
  assert.deepEqual(
    (await repository.list("prj-1")).map((artifact) => artifact.id),
    ["newest", "middle", "older"],
  );
});

test("the http adapter calls the BFF path and parses the wire", async () => {
  let requested: string | undefined;
  let init: RequestInit | undefined;
  const repository = httpDesignArtifactRepository({
    fetchImpl: async (input, requestInit) => {
      requested = String(input);
      init = requestInit;
      return Response.json({
        data: {
          id: "doc-1",
          project_id: "prj one",
          document_id: "doc-1",
          kind: "web",
          title: "Landing page",
          status: "draft",
          current_version_id: "3",
        },
      });
    },
  });
  const artifact = await repository.get("prj one", "doc-1");
  assert.equal(
    requested,
    "/api/clue/api/v1/projects/prj%20one/design-artifacts/doc-1",
  );
  assert.equal(init?.cache, "no-store");
  assert.deepEqual(artifact, {
    id: "doc-1",
    projectId: "prj one",
    documentId: "doc-1",
    kind: "web",
    title: "Landing page",
    currentVersionId: "3",
    status: "draft",
    capabilities: {},
  });
});

test("the http adapter calls the feed path and parses the list wire", async () => {
  let requested: string | undefined;
  let init: RequestInit | undefined;
  const repository = httpDesignArtifactRepository({
    fetchImpl: async (input, requestInit) => {
      requested = String(input);
      init = requestInit;
      return Response.json({
        data: [
          {
            id: "doc-1",
            project_id: "prj one",
            document_id: "doc-1",
            kind: "web",
            title: "Landing page",
            status: "draft",
            current_version_id: "3",
            created_at: "2026-08-14T09:15:00+00:00",
            updated_at: "2026-08-18T09:15:00+00:00",
            origin_thread_id: "thread-9",
          },
        ],
      });
    },
  });
  const artifacts = await repository.list("prj one");
  assert.equal(
    requested,
    "/api/clue/api/v1/projects/prj%20one/design-artifacts",
  );
  assert.equal(init?.cache, "no-store");
  assert.deepEqual(artifacts, [
    {
      id: "doc-1",
      projectId: "prj one",
      documentId: "doc-1",
      kind: "web",
      title: "Landing page",
      currentVersionId: "3",
      status: "draft",
      capabilities: {},
      createdAt: "2026-08-14T09:15:00+00:00",
      updatedAt: "2026-08-18T09:15:00+00:00",
      originThreadId: "thread-9",
    },
  ]);
});

test("the http adapter serves an empty feed as an empty list", async () => {
  const repository = httpDesignArtifactRepository({
    fetchImpl: async () => Response.json({ data: [] }),
  });
  assert.deepEqual(await repository.list("prj-1"), []);
});

test("the http adapter surfaces the backend's typed error envelope", async () => {
  const repository = httpDesignArtifactRepository({
    fetchImpl: async () =>
      Response.json(
        {
          error: {
            code: "ARTIFACT_NOT_FOUND",
            message: "no such design artifact in this workspace",
          },
        },
        { status: 404 },
      ),
  });
  const isTypedRefusal = (error: unknown) =>
    error instanceof DesignArtifactError &&
    error.code === "ARTIFACT_NOT_FOUND" &&
    error.status === 404 &&
    error.message === "no such design artifact in this workspace";
  await assert.rejects(repository.get("prj-1", "doc_missing"), isTypedRefusal);
  await assert.rejects(repository.list("prj-1"), isTypedRefusal);
});
