import assert from "node:assert/strict";
import test from "node:test";
import {
  createHttpProjectWorkspaceRepository,
  getProjectHome,
  getProjectWorkspace,
} from "./project-workspace.repository";

test("project fixtures satisfy the backend handoff contract", async () => {
  const [home, project] = await Promise.all([
    getProjectHome(),
    getProjectWorkspace("10m-landing-page-campaign"),
  ]);

  assert.ok(project);
  assert.equal(home.defaultBrandId, "brand-clue-demo");
  assert.ok(home.composerCapabilities.contextRefs);
  assert.ok(project.artifacts.every((artifact) => artifact.originThreadId));
  assert.ok(project.artifacts.every((artifact) => artifact.originRunId));
  assert.ok(project.models.some((model) => model.id === project.defaultModelId));
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
    assert.deepEqual(project.models, []);
    assert.equal(project.plan, null);
    assert.equal(project.questionnaire, null);
    assert.deepEqual(project.composerCapabilities, {
      agentProfileSelection: false,
      attachments: false,
      contextRefs: false,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
