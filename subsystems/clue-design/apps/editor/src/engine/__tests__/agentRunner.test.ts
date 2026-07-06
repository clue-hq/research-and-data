import { afterEach, describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import { createApiAgentRunner, agentResultFromUnknown } from "../agentRunner";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("agent runner", () => {
  it("posts current scene context to the agent API and normalizes proposals", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          status: "accepted",
          summary: "Created a square ad proposal.",
          run_id: "run_agent_123",
          trace_dir: ".lumen-runs/run_agent_123",
          dsl_blocks: ["page page_square size(1080,1080,px)"],
          operations: [
            {
              kind: "update_document",
              patch: {
                title: { kind: "set", value: "Square Ad" },
                artifact_type: { kind: "unchanged" },
                medium: { kind: "unchanged" },
                brand_kit: { kind: "unchanged" }
              }
            }
          ],
          draft_scene: null,
          stop_reason: null,
          diagnostics: [],
          artifacts: [
            {
              format: "svg",
              page_id: "page_square",
              filename: "page_square.preview.svg",
              path: ".lumen-runs/run_agent_123/page_square.svg",
              mime_type: "image/svg+xml"
            }
          ]
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const runner = createApiAgentRunner({ apiBaseUrl: "http://localhost:8000" });

    const result = await runner({
      prompt: "Create a square ad",
      scene: minimalScene,
      documentId: "doc_agent",
      activePageId: "page_a4",
      targetNodeIds: ["node_contact_name"],
      diagnostics: []
    });

    expect(result.status).toBe("proposed");
    expect(result.summary).toBe("Created a square ad proposal.");
    expect(result.dsl_blocks).toEqual(["page page_square size(1080,1080,px)"]);
    expect(result.operations).toHaveLength(1);
    expect(result.trace).toMatchObject({
      run_id: "run_agent_123",
      trace_dir: ".lumen-runs/run_agent_123"
    });
    expect(result.artifacts[0]).toMatchObject({
      format: "svg",
      page_id: "page_square",
      filename: "page_square.preview.svg"
    });
    expect(fetchMock).toHaveBeenCalledWith(
      new URL("/agent/turn-preview", "http://localhost:8000"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          prompt: "Create a square ad",
          scene: minimalScene,
          document_id: "doc_agent",
          active_page_id: "page_a4",
          target_node_ids: ["node_contact_name"],
          agent_instructions: null,
          model: null,
          diagnostics: []
        })
      })
    );
  });

  it("fails closed on invalid agent payloads", () => {
    const result = agentResultFromUnknown("not an object");

    expect(result.status).toBe("failed");
    expect(result.operations).toEqual([]);
    expect(result.diagnostics[0]).toMatchObject({
      severity: "error",
      code: "EDITOR_AGENT_INVALID_RESPONSE"
    });
  });

  it("keeps unapproved draft scenes visible without marking them as proposals", () => {
    const draftScene = {
      ...minimalScene,
      pages: {
        ...minimalScene.pages,
        page_square: {
          ...minimalScene.pages.page_a4,
          id: "page_square",
          name: "Square Draft",
          size: {
            width: 1080,
            height: 1080,
            unit: "px",
            preset: "custom",
            orientation: "portrait"
          },
          children: []
        }
      }
    };

    const result = agentResultFromUnknown({
      status: "failed",
      summary: "Max iterations reached.",
      operations: [
        {
          kind: "update_document",
          patch: {
            title: { kind: "set", value: "Should not be applyable" },
            artifact_type: { kind: "unchanged" },
            medium: { kind: "unchanged" },
            brand_kit: { kind: "unchanged" }
          }
        }
      ],
      draft_scene: draftScene,
      stop_reason: "max_iterations_reached",
      diagnostics: []
    });

    expect(result.status).toBe("failed");
    expect(result.operations).toHaveLength(1);
    expect(result.draft_scene?.pages.page_square.size.width).toBe(1080);
    expect(result.stop_reason).toBe("max_iterations_reached");
  });
});
