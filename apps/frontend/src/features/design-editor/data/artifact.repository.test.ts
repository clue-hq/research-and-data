import assert from "node:assert/strict";
import test from "node:test";
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
  await assert.rejects(
    repository.get("prj-1", "doc_missing"),
    (error: unknown) =>
      error instanceof DesignArtifactError &&
      error.code === "ARTIFACT_NOT_FOUND" &&
      error.status === 404 &&
      error.message === "no such design artifact in this workspace",
  );
});
