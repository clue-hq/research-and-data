import assert from "node:assert/strict";
import test from "node:test";
import {
  createHttpProjectWorkspaceRepository,
  getProjectHome,
  getProjectWorkspace,
} from "./project-workspace.repository";

test("fixture project shell uses the honest pre-artifact contract", async () => {
  const [home, project] = await Promise.all([
    getProjectHome(),
    getProjectWorkspace("10m-landing-page-campaign"),
  ]);

  assert.ok(project);
  assert.equal(home.defaultBrandId, "brand-clue-demo");
  assert.ok(home.composerCapabilities.contextRefs);
  assert.deepEqual(project.artifacts, []);
  assert.deepEqual(Object.keys(project).sort(), [
    "artifacts",
    "brandId",
    "composerCapabilities",
    "createdAt",
    "id",
    "productId",
    "status",
    "title",
  ]);
  assert.equal(home.suggestions.length, 3);
  assert.ok(home.suggestions.every((suggestion) => suggestion.length > 0));
});

test("HTTP project shell maps only durable data and keeps Gallery empty", async () => {
  const originalFetch = globalThis.fetch;
  let requested = "";
  globalThis.fetch = async (input) => {
    requested = String(input);
    return new Response(JSON.stringify({
      data: {
        id: "prj_real",
        title: "Untitled project",
        brand_id: "brd_real",
        product_id: null,
        status: "active",
        created_at: "2026-08-10T12:00:00Z",
        context_entities: [],
        agent_profiles: [],
        default_agent_profile_id: null,
        composer_capabilities: {
          context_refs: false,
          attachments: false,
          agent_profile_selection: false,
        },
        artifacts: [],
      },
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  try {
    const project = await createHttpProjectWorkspaceRepository({
      mode: "http",
      prefix: "/api/clue",
    }).get("prj_real");
    assert.equal(requested, "/api/clue/api/v1/projects/prj_real");
    assert.equal(project.title, "Untitled project");
    assert.deepEqual(project.artifacts, []);
    assert.equal("models" in project, false);
    assert.equal("plan" in project, false);
    assert.equal("questionnaire" in project, false);
    assert.equal("prompt" in project, false);
    assert.equal("contextEntities" in project, false);
    assert.deepEqual(project.composerCapabilities, {
      agentProfileSelection: false,
      attachments: false,
      contextRefs: false,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
