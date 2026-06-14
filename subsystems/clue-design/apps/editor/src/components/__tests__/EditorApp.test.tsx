import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { BrandKitSummary, Scene } from "@/engine/contracts";
import type { EditorAgentRunner } from "@/engine/agentRunner";
import type { EditorExportRunner } from "@/engine/exportRunner";
import type { EditorPreflightRunner } from "@/engine/preflightRunner";
import { updateDocumentTitle } from "@/engine/operations";
import { WasmEngine, type WasmModule } from "@/engine/wasmEngine";
import { loadWasmModuleFromDisk, wasmArtifactPresent } from "../../test/wasmModule";
import EditorApp, { type EditorAppProps } from "../EditorApp";

vi.mock("../canvas/CanvasSurface", () => ({
  CanvasSurface: ({
    scene,
    activePageId,
    selectedNodeId,
    workspaceViewport,
    onWorkspaceViewportChange,
    workspaceTool,
    onWorkspaceToolChange,
    workspaceFitTarget,
    onWorkspaceFitTargetChange,
    onOpenDiagnostics,
    onOpenExport
  }: {
    scene: Scene;
    activePageId: string | null;
    selectedNodeId: string | null;
    workspaceViewport: { zoom: number; pan: { x: number; y: number } };
    onWorkspaceViewportChange: (next: { zoom: number; pan: { x: number; y: number } }) => void;
    workspaceTool: string;
    onWorkspaceToolChange: (tool: "select" | "hand") => void;
    workspaceFitTarget: string;
    onWorkspaceFitTargetChange: (target: "current" | "all" | "manual") => void;
    onOpenDiagnostics?: () => void;
    onOpenExport?: () => void;
  }) =>
    React.createElement(
      React.Fragment,
      null,
      React.createElement("div", {
        "data-testid": "canvas-selection",
        "data-selected-node": selectedNodeId ?? "",
        "data-page-width": activePageId ? String(scene.pages[activePageId]?.size.width ?? "") : "",
        "data-page-height": activePageId ? String(scene.pages[activePageId]?.size.height ?? "") : "",
        "data-page-unit": activePageId ? scene.pages[activePageId]?.size.unit ?? "" : "",
        "data-page-preset": activePageId ? scene.pages[activePageId]?.size.preset ?? "" : "",
        "data-page-safe-area": activePageId && scene.pages[activePageId]?.safe_area
          ? rectSummary(scene.pages[activePageId].safe_area)
          : "",
        "data-page-bleed": activePageId && scene.pages[activePageId]?.bleed
          ? rectSummary(scene.pages[activePageId].bleed)
          : "",
        "data-page-children": activePageId ? scene.pages[activePageId]?.children.join(",") ?? "" : "",
        "data-selected-computed": selectedNodeId && scene.nodes[selectedNodeId]?.computed
          ? rectSummary(scene.nodes[selectedNodeId].computed.layout_bounds)
          : "",
        "data-workspace-zoom": String(workspaceViewport.zoom),
        "data-workspace-pan": `${workspaceViewport.pan.x},${workspaceViewport.pan.y}`,
        "data-workspace-tool": workspaceTool,
        "data-workspace-fit-target": workspaceFitTarget
      }),
      React.createElement("button", {
        type: "button",
        "data-testid": "mock-workspace-pan-tool",
        onClick: () => onWorkspaceToolChange("hand")
      }),
      React.createElement("button", {
        type: "button",
        "data-testid": "mock-workspace-viewport",
        onClick: () => {
          onWorkspaceFitTargetChange("manual");
          onWorkspaceViewportChange({ zoom: 1.75, pan: { x: 40, y: 60 } });
        }
      }),
      React.createElement("button", {
        type: "button",
        "data-testid": "mock-open-diagnostics",
        onClick: () => onOpenDiagnostics?.()
      }),
      React.createElement("button", {
        type: "button",
        "data-testid": "mock-open-export",
        onClick: () => onOpenExport?.()
      })
    )
}));

// W4: EditorApp requires the WASM engine for local editing (the legacy TS
// mirror is gone). Every render gets a real engine over the same initial
// scene; the suite skips with a notice when the artifact is not built
// (`npm run build:wasm`).
let wasmModule: WasmModule;

function TestEditorApp(props: EditorAppProps) {
  const engine = React.useMemo(
    () => new WasmEngine(wasmModule, props.initialScene ?? minimalScene),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );
  return <EditorApp {...props} optimisticEngine={engine} />;
}

function openInspectorPanel() {
  fireEvent.click(screen.getByRole("button", { name: /^Inspect$/i }));
}

describe.skipIf(!wasmArtifactPresent)("EditorApp", () => {
  beforeAll(async () => {
    wasmModule = await loadWasmModuleFromDisk();
  });

  it("clears stale node selection when switching pages", () => {
    const scene = twoPageScene();
    render(<TestEditorApp initialScene={scene} initialSelectedNodeId="node_contact_name" />);

    expect(screen.getByRole("heading", { name: "Contact Name" })).toBeInTheDocument();
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "node_contact_name");

    fireEvent.click(screen.getByText("Second Page"));

    expect(screen.getByText("Page")).toBeInTheDocument();
    expect(screen.getByText(/Page\/artboard dimensions are canonical scene data/)).toBeInTheDocument();
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "");
  });

  it("edits custom page dimensions through the canonical scene model", () => {
    render(<TestEditorApp initialScene={twoPageScene()} initialSelectedNodeId={null} />);

    fireEvent.change(screen.getByLabelText("W"), {
      target: { value: "1200" }
    });
    fireEvent.change(screen.getByLabelText("H"), {
      target: { value: "628" }
    });
    fireEvent.change(screen.getByLabelText("Unit"), {
      target: { value: "px" }
    });

    const canvas = screen.getByTestId("canvas-selection");
    expect(canvas).toHaveAttribute("data-page-width", "1200");
    expect(canvas).toHaveAttribute("data-page-height", "628");
    expect(canvas).toHaveAttribute("data-page-unit", "pt");
    expect(canvas).toHaveAttribute("data-page-preset", "custom");
    expect(screen.getByText(/1200 x 628 px/)).toBeInTheDocument();
    expect(screen.getAllByText(/update_page/).length).toBeGreaterThan(0);
    expect(screen.getByText(/"preset": "custom"/)).toBeInTheDocument();
  });

  it("edits document metadata through canonical document operations", () => {
    render(<TestEditorApp initialScene={twoPageScene()} initialSelectedNodeId={null} />);

    fireEvent.change(screen.getByLabelText("Document Title"), {
      target: { value: "Neurosurgery LinkedIn Ad" }
    });
    fireEvent.change(screen.getByLabelText("Artifact Type"), {
      target: { value: "linkedin_ad" }
    });

    expect(screen.getByRole("heading", { name: "Neurosurgery LinkedIn Ad" })).toBeInTheDocument();
    expect(screen.getAllByText(/update_document/).length).toBeGreaterThan(0);
    expect(screen.getByText(/"artifact_type":/)).toBeInTheDocument();
    expect(screen.getByText(/"linkedin_ad"/)).toBeInTheDocument();
  });

  it("creates and selects a new arbitrary custom-size page for export", async () => {
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: []
    });
    const preflightRunner = successfulPreflightRunner();
    render(
      <TestEditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={preflightRunner}
      />
    );

    fireEvent.change(screen.getByLabelText("Custom artboard name"), {
      target: { value: "Client Leaderboard" }
    });
    fireEvent.change(screen.getByLabelText("Custom artboard width"), {
      target: { value: "1200" }
    });
    fireEvent.change(screen.getByLabelText("Custom artboard height"), {
      target: { value: "628" }
    });
    fireEvent.change(screen.getByLabelText("Custom artboard unit"), {
      target: { value: "px" }
    });
    fireEvent.click(screen.getByRole("button", { name: /add artboard/i }));

    const canvas = screen.getByTestId("canvas-selection");
    expect(canvas).toHaveAttribute("data-page-width", "1200");
    expect(canvas).toHaveAttribute("data-page-height", "628");
    expect(canvas).toHaveAttribute("data-page-unit", "pt");
    expect(canvas).toHaveAttribute("data-page-preset", "custom");
    expect(screen.getAllByText("Client Leaderboard").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("add_page page_client_leaderboard")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(preflightRunner).toHaveBeenCalled();
    expect(exportRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        pages: expect.objectContaining({
          page_client_leaderboard: expect.objectContaining({
            size: expect.objectContaining({
              width: 1200,
              height: 628,
              unit: "pt",
              preset: "custom",
              source: expect.objectContaining({
                width: 1200,
                height: 628,
                unit: "px"
              }),
              output: expect.objectContaining({
                raster: expect.objectContaining({
                  width_px: 1200,
                  height_px: 628
                })
              })
            })
          })
        })
      }),
      profile: expect.objectContaining({
        name: "preview_svg"
      }),
      pageIds: ["page_client_leaderboard"]
    });
  });

  it("passes the persisted document id to export runners when available", async () => {
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: []
    });

    render(
      <TestEditorApp
        documentId="doc_editor_saved"
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={successfulPreflightRunner(twoPageScene())}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(exportRunner).toHaveBeenCalledWith({
      scene: expect.any(Object),
      pageIds: ["page_a4"],
      profile: expect.objectContaining({
        name: "preview_svg"
      }),
      documentId: "doc_editor_saved"
    });
  });

  it("invalidates export preview artifacts after accepted scene edits", async () => {
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: [
        {
          format: "svg",
          page_id: "page_a4",
          asset_id: null,
          filename: "page_a4.preview_svg.svg",
          sidecar_filename: null,
          mime_type: "image/svg+xml",
          byte_length: 24,
          dimensions: {
            width: 793.7007874015749,
            height: 1122.5196850393702,
            unit: "scene",
            source: "svg_view_box"
          },
          data_url: "data:image/svg+xml;base64,PHN2Zy8+",
          text: "<svg />",
          sidecar_json: null,
          sidecar_summary: null
        }
      ]
    });

    render(
      <TestEditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={successfulPreflightRunner(twoPageScene())}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Compare$/i })).toHaveClass("active");
    expect(screen.getByRole("link", { name: /^download$/i })).toBeInTheDocument();

    openInspectorPanel();
    fireEvent.change(screen.getByLabelText("Document Title"), {
      target: { value: "Edited After Export" }
    });

    expect(screen.queryByText("Export ready")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^download$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Canvas$/i })).toHaveClass("active");
    expect(screen.getByRole("button", { name: /^Compare$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Export Preview$/i })).toBeDisabled();
  });

  it("duplicates custom-sized pages with cloned content through canonical operations", async () => {
    const scene = twoPageScene();
    scene.pages.page_a4.size = {
      width: 1200,
      height: 628,
      unit: "px",
      preset: "custom",
      orientation: "landscape"
    };
    scene.pages.page_a4.safe_area = {
      x: 48,
      y: 48,
      width: 1104,
      height: 532
    };
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: []
    });

    render(
      <TestEditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={successfulPreflightRunner()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /duplicate artboard a4 letter/i }));

    expect((await screen.findAllByText("A4 Letter Copy")).length).toBeGreaterThanOrEqual(1);
    const canvas = screen.getByTestId("canvas-selection");
    expect(canvas).toHaveAttribute("data-page-width", "1200");
    expect(canvas).toHaveAttribute("data-page-height", "628");
    expect(canvas).toHaveAttribute("data-page-unit", "px");
    expect(canvas).toHaveAttribute("data-page-preset", "custom");
    expect(canvas).toHaveAttribute("data-page-safe-area", "48,48,1104,532");
    expect(canvas).toHaveAttribute("data-page-children", "node_contact_name_a4_letter_copy");
    expect(screen.getByText("add_page page_a4_letter_copy")).toBeInTheDocument();
    expect(screen.getByText("insert_node node_contact_name_a4_letter_copy")).toBeInTheDocument();
    expect(screen.getByText("bind_node_to_slot node_contact_name_a4_letter_copy")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Undo$/i }));

    await waitFor(() => {
      expect(screen.queryByText("A4 Letter Copy")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("insert_node node_contact_name_a4_letter_copy")).not.toBeInTheDocument();
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "1200");
    expect(screen.getByRole("button", { name: /^Redo$/i })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: /^Redo$/i }));
    expect(await screen.findByText("A4 Letter Copy")).toBeInTheDocument();
    fireEvent.click(screen.getByText("A4 Letter Copy"));

    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(exportRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        pages: expect.objectContaining({
          page_a4_letter_copy: expect.objectContaining({
            size: expect.objectContaining({
              width: 1200,
              height: 628,
              unit: "px",
              preset: "custom"
            }),
            children: ["node_contact_name_a4_letter_copy"]
          })
        }),
        slots: expect.objectContaining({
          slot_contact_name: expect.objectContaining({
            bound_nodes: expect.arrayContaining([
              "node_contact_name",
              "node_contact_name_a4_letter_copy"
            ])
          })
        })
      }),
      pageIds: ["page_a4_letter_copy"],
      profile: expect.objectContaining({
        name: "preview_svg"
      })
    });
  });

  it("removes pages through canonical page operations and selects a remaining page", () => {
    const scene = twoPageScene();
    scene.pages.page_second.size = {
      width: 600,
      height: 800,
      unit: "px",
      preset: "custom",
      orientation: "portrait"
    };
    render(<TestEditorApp initialScene={scene} initialSelectedNodeId="node_contact_name" />);

    fireEvent.click(screen.getByText("Second Page"));
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "600");

    fireEvent.click(screen.getByRole("button", { name: /remove artboard second page/i }));

    const canvas = screen.getByTestId("canvas-selection");
    expect(canvas).toHaveAttribute("data-page-width", "210");
    expect(canvas).toHaveAttribute("data-page-height", "297");
    expect(canvas).toHaveAttribute("data-selected-node", "");
    expect(screen.queryByRole("button", { name: /second page/i })).not.toBeInTheDocument();
    expect(screen.getByText("remove_page page_second")).toBeInTheDocument();
  });

  it("previews slot fixture content by applying canonical text node operations", () => {
    render(<TestEditorApp initialScene={twoPageScene()} initialSelectedNodeId="node_contact_name" />);

    fireEvent.click(screen.getAllByRole("button", { name: "Apply to text node" })[1]);

    expect(screen.getByLabelText("Content")).toHaveValue("Dr. Maximilian Alexander Whitmore");
    expect(screen.getByText("update_node node_contact_name")).toBeInTheDocument();
    expect(screen.getByText(/"content": "Dr. Maximilian Alexander Whitmore"/)).toBeInTheDocument();
  });

  it("applies multi-node slot previews as one undoable editor action", () => {
    render(<TestEditorApp initialScene={sceneWithMultiBoundTextSlot()} initialSelectedNodeId="node_contact_name" />);

    fireEvent.click(screen.getAllByRole("button", { name: "Apply to text nodes" })[1]);

    expect(screen.getByLabelText("Content")).toHaveValue("Dr. Maximilian Alexander Whitmore");
    expect(screen.getByText("update_node node_contact_name")).toBeInTheDocument();
    expect(screen.getByText("update_node node_contact_secondary")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /select layer secondary contact name/i }));
    expect(screen.getByLabelText("Content")).toHaveValue("Dr. Maximilian Alexander Whitmore");

    fireEvent.click(screen.getByRole("button", { name: /^Undo$/i }));

    expect(screen.getByLabelText("Content")).toHaveValue("Original Secondary Contact");
    expect(screen.queryByText("update_node node_contact_name")).not.toBeInTheDocument();
    expect(screen.queryByText("update_node node_contact_secondary")).not.toBeInTheDocument();
    expect(screen.getByText("1 action available to redo.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Redo$/i }));

    expect(screen.getByLabelText("Content")).toHaveValue("Dr. Maximilian Alexander Whitmore");
    expect(screen.getByText("update_node node_contact_name")).toBeInTheDocument();
    expect(screen.getByText("update_node node_contact_secondary")).toBeInTheDocument();
  });

  it("surfaces page-focused canvas preview approximation notes separately from local diagnostics", () => {
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    scene.pages.page_a4.background = [
      {
        id: "page_brand_gradient",
        paint: {
          kind: "linear_gradient",
          angle: 90,
          stops: [
            {
              color: {
                kind: "token",
                token: "surface.brand"
              },
              position: 0
            },
            {
              color: {
                kind: "hex",
                value: "#ffffff"
              },
              position: 1
            }
          ]
        }
      }
    ];

    render(<TestEditorApp initialScene={scene} initialSelectedNodeId={null} />);

    expect(screen.getByText("No local diagnostics.")).toBeInTheDocument();
    expect(screen.getByText("Focused diagnostics")).toBeInTheDocument();
    const focused = screen.getByRole("list", { name: "Focused diagnostics" });
    expect(within(focused).getByText("EDITOR_RENDER_GRADIENT_APPROXIMATION")).toBeInTheDocument();
    expect(within(focused).getByText("EDITOR_RENDER_TOKEN_FALLBACK")).toBeInTheDocument();
    expect(screen.getByText(/Issues tied to the selected node, current page/)).toBeInTheDocument();
  });

  it("runs canonical preflight, surfacing diagnostics while geometry stays editor-coherent", async () => {
    // The server preflight returns authoritative Skia geometry (width 320),
    // but the editor owns a single coherent coordinate model: the in-browser
    // engine relays out every scene it loads with the heuristic measurer, so
    // render and edit always agree. The Skia geometry is NOT rendered (it
    // would jump on the next local edit — the desync this fix removes); it
    // governs export fidelity, and the editor/export gap closes in Wave 3
    // (Skia-in-browser). So the selected node's rendered computed stays the
    // editor-relaid heuristic value across the preflight round-trip.
    const preflightedScene = twoPageScene();
    preflightedScene.nodes.node_contact_name.computed = {
      layout_bounds: {
        x: 24,
        y: 40,
        width: 320,
        height: 48
      },
      render_bounds: {
        x: 24,
        y: 40,
        width: 320,
        height: 48
      }
    };
    const preflightRunner: EditorPreflightRunner = vi.fn().mockResolvedValue({
      status: "applied",
      diagnostics: [],
      scene: preflightedScene,
      preflight: {
        has_errors: false,
        brand_ref_operations: 1,
        token_operations: 2,
        layout_operations: 3
      },
      brand_kit: {
        source: "platform_default",
        id: "brand_kit_platform_default",
        version: 1,
        name: "Platform Default"
      }
    });

    render(
      <TestEditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId="node_contact_name"
        preflightRunner={preflightRunner}
      />
    );

    // At mount the engine has already relaid the scene, so the selection
    // renders coherent heuristic geometry (width 160), never empty/stale.
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute(
      "data-selected-computed",
      "24,40,160,28"
    );

    fireEvent.click(screen.getByRole("button", { name: /^Validate$/i }));

    expect(await screen.findByText("Preflight applied")).toBeInTheDocument();
    expect(screen.getByText(/6 operations · Brand platform_default/)).toBeInTheDocument();
    expect(screen.getByText(/Preflight applied 6 canonical operations/)).toBeInTheDocument();
    // Preflight's authoritative Skia geometry (width 320) is not adopted for
    // render: replaceScene reloads through the engine, which relays out to the
    // editor's heuristic, keeping the single coherent coordinate model.
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute(
      "data-selected-computed",
      "24,40,160,28"
    );
    expect(preflightRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        pages: expect.objectContaining({
          page_a4: expect.any(Object)
        })
      })
    });
  });

  it("lets users chat with the agent, inspect proposed operations, and apply them through preview", async () => {
    const agentRunner: EditorAgentRunner = vi.fn().mockResolvedValue({
      status: "proposed",
      summary: "I proposed a tighter headline for the current page.",
      dsl_blocks: ["#node_contact_name text \"Agent authored headline\""],
      operations: [updateDocumentTitle("Agent Authored Ad")],
      draft_scene: null,
      stop_reason: null,
      diagnostics: [],
      trace: {
        run_id: "run_agent_editor",
        trace_dir: ".lumen-runs/run_agent_editor",
        preview_paths: []
      },
      artifacts: []
    });
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: [
        {
          format: "svg",
          page_id: "page_a4",
          asset_id: null,
          filename: "page_a4.preview_svg.svg",
          sidecar_filename: null,
          mime_type: "image/svg+xml",
          byte_length: 24,
          dimensions: {
            width: 210,
            height: 297,
            unit: "scene",
            source: "svg_view_box"
          },
          data_url: "data:image/svg+xml;base64,PHN2Zy8+",
          text: "<svg />",
          sidecar_json: null,
          sidecar_summary: null
        }
      ]
    });
    const preflightRunner = successfulPreflightRunner();

    render(
      <TestEditorApp
        documentId="doc_agent_editor"
        initialScene={twoPageScene()}
        initialSelectedNodeId="node_contact_name"
        agentRunner={agentRunner}
        exportRunner={exportRunner}
        preflightRunner={preflightRunner}
      />
    );

    expect(screen.getByRole("button", { name: /^Agent$/i })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("complementary", { name: "Inspector sidebar" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Agent$/i }));
    expect(screen.getByRole("button", { name: /^Agent$/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("complementary", { name: "Agent chat sidebar" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Message the agent"), {
      target: {
        value: "Make the selected headline clearer."
      }
    });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/i }));

    expect(await screen.findAllByText("I proposed a tighter headline for the current page.")).toHaveLength(2);
    expect(screen.getByText("Proposal ready")).toBeInTheDocument();
    expect(screen.getByText("#node_contact_name text \"Agent authored headline\"")).toBeInTheDocument();
    expect(screen.getAllByText("update_document").length).toBeGreaterThan(0);
    expect(screen.getByText("run_agent_editor")).toBeInTheDocument();
    expect(screen.getByText(".lumen-runs/run_agent_editor")).toBeInTheDocument();
    expect(agentRunner).toHaveBeenCalledWith({
      prompt: "Make the selected headline clearer.",
      scene: expect.objectContaining({
        pages: expect.objectContaining({
          page_a4: expect.any(Object)
        })
      }),
      documentId: "doc_agent_editor",
      activePageId: "page_a4",
      selectedNodeId: "node_contact_name",
      diagnostics: []
    });

    fireEvent.click(screen.getByRole("button", { name: /^Apply and preview$/i }));

    expect(await screen.findByRole("heading", { name: "Agent Authored Ad" })).toBeInTheDocument();
    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(preflightRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        meta: expect.objectContaining({
          title: "Agent Authored Ad"
        })
      })
    });
    expect(exportRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        meta: expect.objectContaining({
          title: "Agent Authored Ad"
        })
      }),
      pageIds: ["page_a4"],
      profile: expect.objectContaining({
        name: "preview_svg"
      }),
      documentId: "doc_agent_editor"
    });
  });

  it("surfaces failed agent responses without applying operations", async () => {
    const agentRunner: EditorAgentRunner = vi.fn().mockResolvedValue({
      status: "failed",
      summary: "The agent runtime could not produce valid DSL.",
      dsl_blocks: [],
      operations: [],
      draft_scene: null,
      stop_reason: "compiler_halt",
      diagnostics: [
        {
          severity: "error",
          phase: "dsl",
          code: "LUMA_AGENT_COMPILE_FAILED",
          message: "The generated DSL halted before producing operations.",
          subject: {
            kind: "document"
          },
          hint: "Ask the agent for a smaller repair block."
        }
      ],
      trace: {
        run_id: "run_agent_failed",
        trace_dir: null,
        preview_paths: []
      },
      artifacts: []
    });

    render(
      <TestEditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        agentRunner={agentRunner}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /^Agent$/i }));
    fireEvent.change(screen.getByLabelText("Message the agent"), {
      target: {
        value: "Try an impossible change."
      }
    });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/i }));

    expect(await screen.findByText("Agent blocked")).toBeInTheDocument();
    expect(screen.getAllByText("LUMA_AGENT_COMPILE_FAILED").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /^Apply and preview$/i })).toBeDisabled();
    expect(screen.getByRole("heading", { name: "Hospital Letter" })).toBeInTheDocument();
  });

  it("shows the latest unapproved agent draft on the canvas when the loop is blocked", async () => {
    const draftScene = twoPageScene();
    draftScene.pages.page_square = {
      ...draftScene.pages.page_a4,
      id: "page_square",
      name: "Agent Square Draft",
      size: {
        width: 1080,
        height: 1080,
        unit: "px",
        preset: "custom",
        orientation: "portrait"
      },
      children: []
    };
    const agentRunner: EditorAgentRunner = vi.fn().mockResolvedValue({
      status: "failed",
      summary: "Maximum repair iterations reached, but a draft is available.",
      dsl_blocks: ["page page_square size(1080,1080,px)"],
      operations: [],
      draft_scene: draftScene,
      stop_reason: "max_iterations_reached",
      diagnostics: [
        {
          severity: "error",
          phase: "layout",
          code: "LUMA_AGENT_MAX_ITERATIONS",
          message: "The agent did not reach final acceptance.",
          subject: { kind: "document" },
          hint: "Inspect the draft and repair manually."
        }
      ],
      trace: {
        run_id: "run_agent_draft",
        trace_dir: ".lumen-runs/run_agent_draft",
        preview_paths: []
      },
      artifacts: []
    });

    render(
      <TestEditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        agentRunner={agentRunner}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /^Agent$/i }));
    fireEvent.change(screen.getByLabelText("Message the agent"), {
      target: {
        value: "Make a square ad."
      }
    });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/i }));

    expect(await screen.findByText("Draft visible")).toBeInTheDocument();
    expect(screen.getByText(/latest unapproved draft is shown on the canvas/i)).toBeInTheDocument();
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "1080");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-height", "1080");
    expect(screen.getAllByText(/latest unapproved draft is shown on the canvas/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /^Draft already shown$/i })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /^Undo$/i }));

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "210");
  });

  it("swaps the inspector for a resizable agent chat right sidebar", async () => {
    render(<TestEditorApp initialScene={twoPageScene()} initialSelectedNodeId={null} />);

    const topContext = screen.getByLabelText("Active artboard context");
    expect(within(topContext).getByText("A4 Letter")).toBeInTheDocument();
    expect(within(topContext).getByText(/793.7 x 1122.5 pt · 100%/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Inspect$/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("complementary", { name: "Inspector sidebar" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Message the agent")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Agent$/i }));
    expect(screen.getByRole("button", { name: /^Inspect$/i })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: /^Agent$/i })).toHaveAttribute("aria-pressed", "true");

    const workspace = document.querySelector(".workspace-grid");
    expect(workspace).toHaveClass("agent-open");
    expect(workspace?.getAttribute("style")).toContain("--right-sidebar-width: 420px");
    expect(screen.queryByText(/^Inspector$/i)).not.toBeInTheDocument();

    fireEvent(
      screen.getByRole("separator", { name: /resize agent chat sidebar/i }),
      new MouseEvent("pointerdown", {
        bubbles: true,
        clientX: 900
      })
    );
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 800 }));
    window.dispatchEvent(new Event("pointerup"));

    await waitFor(() =>
      expect(workspace?.getAttribute("style")).toContain("--right-sidebar-width: 520px")
    );
    expect(screen.getByRole("complementary", { name: "Agent chat sidebar" })).toBeInTheDocument();
  });

  it("keeps workspace viewport and tool state across export preview transitions", async () => {
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: [
        {
          format: "svg",
          page_id: "page_a4",
          asset_id: null,
          filename: "page_a4.preview_svg.svg",
          sidecar_filename: null,
          mime_type: "image/svg+xml",
          byte_length: 24,
          dimensions: {
            width: 210,
            height: 297,
            unit: "scene",
            source: "svg_view_box"
          },
          data_url: "data:image/svg+xml;base64,PHN2Zy8+",
          text: "<svg />",
          sidecar_json: null,
          sidecar_summary: null
        }
      ]
    });

    render(
      <TestEditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={successfulPreflightRunner(twoPageScene())}
      />
    );

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-tool", "select");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-fit-target", "all");

    fireEvent.click(screen.getByTestId("mock-workspace-pan-tool"));
    fireEvent.click(screen.getByTestId("mock-workspace-viewport"));

    await waitFor(() => {
      expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-tool", "hand");
      expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-fit-target", "manual");
      expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-zoom", "1.75");
      expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-pan", "40,60");
    });
    expect(screen.getByText("No operation emitted yet.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Compare$/i })).toHaveClass("active");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-tool", "hand");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-fit-target", "manual");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-zoom", "1.75");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-pan", "40,60");

    fireEvent.click(screen.getByRole("button", { name: /^Canvas$/i }));

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-tool", "hand");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-fit-target", "manual");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-zoom", "1.75");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-workspace-pan", "40,60");
    fireEvent.click(screen.getByRole("button", { name: /^Inspect$/i }));
    expect(screen.getByText("No operation emitted yet.")).toBeInTheDocument();
  });

  it("opens diagnostics and export panel modes from workspace toolbar callbacks", () => {
    render(<TestEditorApp initialScene={twoPageScene()} initialSelectedNodeId={null} />);

    fireEvent.click(screen.getByTestId("mock-open-diagnostics"));

    expect(screen.getByRole("complementary", { name: "Diagnostics sidebar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /diagnostics panel/i })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByTestId("mock-open-export"));

    expect(screen.getByRole("complementary", { name: "Export sidebar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export panel/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("preserves active artboard and selected node across top mode switches", () => {
    render(<TestEditorApp initialScene={twoPageScene()} initialSelectedNodeId="node_contact_name" />);

    for (const modeButton of [
      screen.getByRole("button", { name: /export panel/i }),
      screen.getByRole("button", { name: /diagnostics panel/i }),
      screen.getByRole("button", { name: /^Agent$/i }),
      screen.getByRole("button", { name: /^Inspect$/i })
    ]) {
      fireEvent.click(modeButton);
      expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "node_contact_name");
      expect(within(screen.getByLabelText("Active artboard context")).getByText("A4 Letter")).toBeInTheDocument();
    }
  });

  it("undoes and redoes accepted editor operations through scene snapshots", () => {
    render(<TestEditorApp initialScene={twoPageScene()} initialSelectedNodeId={null} />);

    expect(screen.getByRole("button", { name: /^Undo$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Redo$/i })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("W"), {
      target: { value: "1200" }
    });

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "1200");
    expect(screen.getByText("update_page page_a4")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Undo$/i }));

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "210");
    expect(screen.getByText("1 action available to redo.")).toBeInTheDocument();
    expect(screen.queryByText("update_page page_a4")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Redo$/i }));

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "1200");
    expect(screen.getByText("update_page page_a4")).toBeInTheDocument();
    expect(screen.queryByText("action available to redo.")).not.toBeInTheDocument();
  });

  it("supports keyboard undo and redo without requiring a selected node", () => {
    render(<TestEditorApp initialScene={twoPageScene()} initialSelectedNodeId={null} />);

    fireEvent.change(screen.getByLabelText("W"), {
      target: { value: "1200" }
    });

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "1200");

    fireEvent.keyDown(window, { key: "z", metaKey: true });
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "210");

    fireEvent.keyDown(window, { key: "z", metaKey: true, shiftKey: true });
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "1200");

    fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "210");

    fireEvent.keyDown(window, { key: "y", ctrlKey: true });
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "1200");
  });

  it("clears selection with Escape without mutating the scene", () => {
    render(<TestEditorApp initialScene={sceneWithTwoLayerNodes()} initialSelectedNodeId="node_contact_name" />);

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "node_contact_name");
    expect(screen.getByRole("heading", { name: "Contact Name" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "");
    expect(screen.queryByRole("heading", { name: "Contact Name" })).not.toBeInTheDocument();
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-children", "node_contact_name,node_cta_box");
  });

  it("nudges and deletes the selected node with keyboard shortcuts", () => {
    render(<TestEditorApp initialScene={sceneWithTwoLayerNodes()} initialSelectedNodeId="node_contact_name" />);

    expect(screen.getByLabelText("X")).toHaveValue(24);
    expect(screen.getByLabelText("Y")).toHaveValue(40);

    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByLabelText("X")).toHaveValue(25);
    expect(screen.getByText("update_node node_contact_name")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "ArrowDown", shiftKey: true });
    expect(screen.getByLabelText("Y")).toHaveValue(50);

    fireEvent.keyDown(window, { key: "Delete" });
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-children", "node_cta_box");
    expect(screen.getByText("remove_node node_contact_name")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Contact Name" })).not.toBeInTheDocument();
  });

  it("deletes the selected node from the inspector and clears stale selection", () => {
    render(<TestEditorApp initialScene={sceneWithTwoLayerNodes()} initialSelectedNodeId="node_contact_name" />);

    expect(screen.getByRole("heading", { name: "Contact Name" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /delete/i }));

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-children", "node_cta_box");
    expect(screen.getByText("remove_node node_contact_name")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Contact Name" })).not.toBeInTheDocument();
  });

  it("edits safe area and bleed guides as canonical page data", () => {
    const scene = twoPageScene();
    scene.pages.page_a4.size = {
      width: 1080,
      height: 1080,
      unit: "px",
      preset: "custom",
      orientation: "landscape"
    };
    render(<TestEditorApp initialScene={scene} initialSelectedNodeId={null} />);

    fireEvent.change(screen.getByLabelText("Safe Margin"), {
      target: { value: "72" }
    });
    fireEvent.change(screen.getByLabelText("Bleed"), {
      target: { value: "18" }
    });

    const canvas = screen.getByTestId("canvas-selection");
    expect(canvas).toHaveAttribute("data-page-safe-area", "72,72,936,936");
    expect(canvas).toHaveAttribute("data-page-bleed", "-18,-18,1116,1116");
    expect(screen.getAllByText(/update_page/).length).toBeGreaterThan(0);
  });

  it("selects and reorders layers through move_node operations", () => {
    render(<TestEditorApp initialScene={sceneWithTwoLayerNodes()} initialSelectedNodeId={null} />);

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute(
      "data-page-children",
      "node_contact_name,node_cta_box"
    );

    fireEvent.click(screen.getByRole("button", { name: /select layer CTA Box/i }));

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "node_cta_box");

    fireEvent.click(screen.getByRole("button", { name: /move Contact Name down/i }));

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute(
      "data-page-children",
      "node_cta_box,node_contact_name"
    );
    expect(screen.getAllByText(/move_node/).length).toBeGreaterThan(0);
  });

  it("blocks layer reorder controls for locked nodes", () => {
    const scene = sceneWithTwoLayerNodes();
    scene.nodes.node_contact_name.locked = true;

    render(<TestEditorApp initialScene={scene} initialSelectedNodeId={null} />);

    expect(screen.getByText(/text · locked/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Contact Name cannot move down/i })).toBeDisabled();
    expect(screen.queryByText(/move_node/)).not.toBeInTheDocument();
  });

  it("labels children ordered inside auto-layout containers", () => {
    const scene = sceneWithAutoLayoutLayers();

    render(<TestEditorApp initialScene={scene} initialSelectedNodeId={null} />);

    expect(screen.getByText(/text · layout order/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Move Contact Name down/i })).toBeEnabled();
  });

  it("attaches a Brand Kit through an update_document operation", () => {
    render(
      <TestEditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        initialAvailableBrandKits={[brandKitSummary()]}
      />
    );

    fireEvent.change(screen.getByLabelText("Brand Kit"), {
      target: { value: "brand_kit_insight_health@4" }
    });

    expect(screen.getByText("brand_kit_insight_health v4")).toBeInTheDocument();
    expect(screen.getAllByText(/update_document/).length).toBeGreaterThan(0);
  });

  it("exports the active page through the editor export runner", async () => {
    const svgText =
      '<svg viewBox="0 0 793.7007874015749 1122.5196850393702"><text data-lumen-node-id="node_contact_name">Dr. Priya Sharma</text></svg>';
    const sidecarJson = JSON.stringify({
      profile_name: "preview_svg",
      page_ids: ["page_a4"],
      node_count: 1
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText
      },
      configurable: true
    });
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: [
        {
          format: "svg",
          page_id: "page_a4",
          asset_id: null,
          filename: "page_a4.preview_svg.svg",
          sidecar_filename: "page_a4.preview_svg.sidecar.json",
          mime_type: "image/svg+xml",
          byte_length: 120,
          dimensions: {
            width: 793.7007874015749,
            height: 1122.5196850393702,
            unit: "scene",
            source: "svg_view_box"
          },
          data_url: "data:image/svg+xml;base64,PHN2Zy8+",
          text: svgText,
          sidecar_json: sidecarJson,
          sidecar_summary: {
            profile_name: "preview_svg",
            page_count: 1,
            node_count: 1,
            slot_count: 1,
            page_ids: ["page_a4"],
            slot_keys: ["contact.full_name"]
          }
        }
      ]
    });
    const preflightedScene = twoPageScene();
    preflightedScene.nodes.node_contact_name.computed = {
      layout_bounds: {
        x: 24,
        y: 40,
        width: 300,
        height: 32
      },
      render_bounds: {
        x: 24,
        y: 40,
        width: 300,
        height: 32
      }
    };
    const preflightRunner = successfulPreflightRunner(preflightedScene);

    render(
      <TestEditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={preflightRunner}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Compare$/i })).toHaveClass("active");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "210");
    expect(screen.getByText(/SVG artboard page_a4/)).toBeInTheDocument();
    expect(screen.getByText(/image\/svg\+xml · 120 bytes/)).toBeInTheDocument();
    expect(screen.getByText("Filename page_a4.preview_svg.svg")).toBeInTheDocument();
    expect(screen.getByText(/Dimensions 793.70 x 1122.52 scene · svg_view_box/)).toBeInTheDocument();
    expect(screen.getByText(/Sidecar preview_svg · 1 artboard · 1 node · 1 slot/)).toBeInTheDocument();
    expect(screen.getAllByText(/slots contact.full_name/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("link", { name: /^download$/i })).toHaveAttribute("href", "data:image/svg+xml;base64,PHN2Zy8+");
    expect(screen.getByRole("link", { name: /download sidecar/i })).toHaveAttribute(
      "download",
      "page_a4.preview_svg.sidecar.json"
    );
    expect(screen.getByRole("link", { name: /download sidecar/i })).toHaveAttribute(
      "href",
      `data:application/json;charset=utf-8,${encodeURIComponent(sidecarJson)}`
    );
    fireEvent.click(screen.getByRole("button", { name: /copy svg/i }));
    expect(writeText).toHaveBeenCalledWith(svgText);
    expect(await screen.findByText("SVG copied")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /copy sidecar/i }));
    expect(writeText).toHaveBeenCalledWith(sidecarJson);
    expect(await screen.findByText("Sidecar copied")).toBeInTheDocument();
    expect(screen.getByText("Parity OK")).toBeInTheDocument();
    expect(screen.getByText(/Canvas 793.70 x 1122.52 · Export 793.70 x 1122.52/)).toBeInTheDocument();
    expect(exportRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        nodes: expect.objectContaining({
          node_contact_name: expect.objectContaining({
            computed: expect.objectContaining({
              layout_bounds: expect.objectContaining({
                width: 300
              })
            })
          })
        }),
        pages: expect.objectContaining({
          page_a4: expect.any(Object)
        })
      }),
      profile: expect.objectContaining({
        name: "preview_svg",
        format: "svg"
      }),
      pageIds: ["page_a4"]
    });
  });

  it("exports all current pages through the preflighted scene path", async () => {
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: []
    });
    const scene = twoPageScene();
    const preflightRunner = successfulPreflightRunner(scene);

    render(
      <TestEditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={preflightRunner}
      />
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Artboards" }), {
      target: { value: "all" }
    });
    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(preflightRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        pages: expect.objectContaining({
          page_a4: expect.any(Object),
          page_second: expect.any(Object)
        })
      })
    });
    expect(exportRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        pages: expect.objectContaining({
          page_a4: expect.any(Object),
          page_second: expect.any(Object)
        })
      }),
      pageIds: ["page_a4", "page_second"],
      profile: expect.objectContaining({
        name: "preview_svg"
      })
    });
  });

  it("sends print export profiles with readiness warnings", async () => {
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: []
    });

    const scene = twoPageScene();
    scene.pages.page_a4.safe_area = null;
    if (scene.nodes.node_contact_name.kind.kind === "text") {
      scene.nodes.node_contact_name.kind = {
        ...scene.nodes.node_contact_name.kind,
        content: "مرحبا",
        direction: "rtl"
      };
    }
    render(
      <TestEditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={successfulPreflightRunner(scene)}
      />
    );

    fireEvent.change(screen.getByLabelText("Profile"), {
      target: { value: "print_pdf" }
    });

    expect(screen.getByText("PRINT_BLEED_page_a4")).toBeInTheDocument();
    expect(screen.getByText("PRINT_SAFE_AREA_page_a4")).toBeInTheDocument();
    expect(screen.getByText("PRINT_TEXT_DIRECTION_node_contact_name")).toBeInTheDocument();
    expect(screen.getByText("PRINT_TEXT_NON_LATIN_node_contact_name")).toBeInTheDocument();
    expect(screen.getByText("PRINT_FONT_EMBEDDING")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /show node node_contact_name/i })[0]);
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "node_contact_name");
    expect(screen.getByRole("complementary", { name: "Diagnostics sidebar" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /export panel/i }));

    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(exportRunner).toHaveBeenCalledWith({
      scene: expect.any(Object),
      pageIds: ["page_a4"],
      profile: expect.objectContaining({
        name: "print_pdf",
        format: "pdf",
        pdf_intent: "print",
        include_bleed: true,
        embed_fonts: true
      })
    });
  });

  it("warns when print PDF export uses explicit mixed-size pages", () => {
    const scene = twoPageScene();
    scene.pages.page_a4.name = "Square Ad";
    scene.pages.page_a4.size = {
      width: 1080,
      height: 1080,
      unit: "px",
      preset: "custom",
      orientation: "portrait"
    };
    scene.pages.page_a4.safe_area = {
      x: 72,
      y: 72,
      width: 936,
      height: 936
    };
    scene.pages.page_second.name = "Wide Header";
    scene.pages.page_second.size = {
      width: 1200,
      height: 628,
      unit: "px",
      preset: "custom",
      orientation: "landscape"
    };
    scene.pages.page_second.safe_area = {
      x: 48,
      y: 48,
      width: 1104,
      height: 532
    };

    render(<TestEditorApp initialScene={scene} initialSelectedNodeId={null} />);

    fireEvent.change(screen.getByLabelText("Profile"), {
      target: { value: "print_pdf" }
    });
    fireEvent.change(screen.getAllByLabelText("Artboards")[0], {
      target: { value: "all" }
    });

    expect(screen.getByText("PRINT_EXPLICIT_PAGINATION")).toBeInTheDocument();
    expect(screen.getByText(/This print PDF exports 2 explicit artboards/)).toBeInTheDocument();
    expect(screen.getByText("PRINT_MIXED_PAGE_SIZES")).toBeInTheDocument();
    expect(screen.getByText(/Square Ad 1080 x 1080 px; Wide Header 1200 x 628 px/)).toBeInTheDocument();
  });

  it("edits and saves export profile settings before export", async () => {
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: []
    });
    const scene = twoPageScene();
    scene.export_profiles = [];
    render(
      <TestEditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={successfulPreflightRunner(scene)}
      />
    );

    fireEvent.change(screen.getByLabelText("Profile"), {
      target: { value: "preview_png" }
    });
    fireEvent.change(screen.getByLabelText("Profile name"), {
      target: { value: "Client Social PNG" }
    });
    expect(screen.getByText("client_social_png (png, unsaved)")).toBeInTheDocument();
    expect(screen.getByText(/This profile is an unsaved draft/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Scale"), {
      target: { value: "3" }
    });
    fireEvent.change(screen.getByLabelText("DPI"), {
      target: { value: "300" }
    });

    fireEvent.click(screen.getByRole("button", { name: /save profile/i }));

    expect(screen.getByText("1 document export profile saved.")).toBeInTheDocument();
    expect(screen.getByText("upsert_export_profile client_social_png")).toBeInTheDocument();
    expect(screen.getByLabelText("Profile")).toHaveValue("client_social_png");
    expect(screen.queryByText(/This profile is an unsaved draft/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(exportRunner).toHaveBeenCalledWith({
      scene: expect.any(Object),
      pageIds: ["page_a4"],
      profile: expect.objectContaining({
        name: "client_social_png",
        format: "png",
        raster: {
          scale: 3,
          dpi: 300
        },
        pdf_intent: null,
        include_bleed: false,
        embed_fonts: false
      })
    });
  });

  it("warns before exporting oversized custom pages as PNG rasters", () => {
    const scene = twoPageScene();
    scene.pages.page_a4.name = "Huge Square";
    scene.pages.page_a4.size = {
      width: 5000,
      height: 5000,
      unit: "px",
      preset: "custom",
      orientation: "portrait"
    };

    render(<TestEditorApp initialScene={scene} initialSelectedNodeId={null} />);

    fireEvent.change(screen.getByLabelText("Profile"), {
      target: { value: "high_res_png" }
    });

    expect(screen.getByText("PNG_RASTER_SIZE_page_a4")).toBeInTheDocument();
    expect(screen.getByText(/Huge Square will export to 10000 x 10000 px \(100.0 MP\) with high_res_png/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /show artboard page_a4/i }));
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-width", "5000");
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-page-height", "5000");
  });

  it("exports a preview for inspection when canonical preflight fails", async () => {
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: [
        {
          format: "svg",
          page_id: "page_a4",
          asset_id: null,
          filename: "page_a4.preview_svg.svg",
          sidecar_filename: null,
          mime_type: "image/svg+xml",
          byte_length: 24,
          dimensions: {
            width: 210,
            height: 297,
            unit: "scene",
            source: "svg_view_box"
          },
          data_url: "data:image/svg+xml;base64,PHN2Zy8+",
          text: "<svg />",
          sidecar_json: null,
          sidecar_summary: null
        }
      ]
    });
    const preflightRunner: EditorPreflightRunner = vi.fn().mockResolvedValue({
      status: "failed",
      diagnostics: [
        {
          severity: "error",
          phase: "layout",
          code: "LUMV_TEXT_OVERFLOW",
          message: "Headline overflows its frame.",
          subject: {
            kind: "node",
            id: "node_contact_name"
          },
          hint: "Reduce font size or enlarge the text frame."
        }
      ],
      scene: null,
      preflight: {
        has_errors: true,
        brand_ref_operations: 0,
        token_operations: 0,
        layout_operations: 0
      },
      brand_kit: {
        source: "platform_default",
        id: "brand_kit_platform_default",
        version: 1,
        name: "Platform Default"
      }
    });

    render(
      <TestEditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={preflightRunner}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect((await screen.findAllByText("LUMV_TEXT_OVERFLOW")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Headline overflows its frame.").length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(screen.getByText("Not ready for approval")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /show node node_contact_name/i })[0]);
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "node_contact_name");
    expect(exportRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        pages: expect.objectContaining({
          page_a4: expect.any(Object)
        })
      }),
      profile: expect.objectContaining({
        name: "preview_svg"
      }),
      pageIds: ["page_a4"]
    });
  });

  it("exports a preview when preflight summary reports errors even if status is applied", async () => {
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "ok",
      diagnostics: [],
      artifacts: [
        {
          format: "svg",
          page_id: "page_a4",
          asset_id: null,
          filename: "page_a4.preview_svg.svg",
          sidecar_filename: null,
          mime_type: "image/svg+xml",
          byte_length: 24,
          dimensions: {
            width: 210,
            height: 297,
            unit: "scene",
            source: "svg_view_box"
          },
          data_url: "data:image/svg+xml;base64,PHN2Zy8+",
          text: "<svg />",
          sidecar_json: null,
          sidecar_summary: null
        }
      ]
    });
    const preflightRunner: EditorPreflightRunner = vi.fn(({ scene }) =>
      Promise.resolve({
        status: "applied" as const,
        diagnostics: [
          {
            severity: "warning" as const,
            phase: "layout" as const,
            code: "LUMV_PREFLIGHT_HAS_ERRORS",
            message: "Preflight summary reports unresolved layout errors.",
            subject: {
              kind: "document" as const
            },
            hint: "Fix preflight errors before exporting."
          }
        ],
        scene,
        preflight: {
          has_errors: true,
          brand_ref_operations: 0,
          token_operations: 0,
          layout_operations: 0
        },
        brand_kit: {
          source: "platform_default",
          id: "brand_kit_platform_default",
          version: 1,
          name: "Platform Default"
        }
      })
    );

    render(
      <TestEditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={preflightRunner}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect((await screen.findAllByText("LUMV_PREFLIGHT_HAS_ERRORS")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Preflight summary reports unresolved layout errors.").length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByText("Export ready")).toBeInTheDocument();
    expect(screen.getAllByText("EDITOR_EXPORT_PREFLIGHT_HAS_ERRORS").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Not ready for approval")).toBeInTheDocument();
    expect(exportRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        pages: expect.objectContaining({
          page_a4: expect.any(Object)
        })
      }),
      profile: expect.objectContaining({
        name: "preview_svg"
      }),
      pageIds: ["page_a4"]
    });
  });

  it("promotes selected-node diagnostics into a focused diagnostics section", async () => {
    const scene = sceneWithTwoLayerNodes();
    const preflightRunner: EditorPreflightRunner = vi.fn().mockResolvedValue({
      status: "failed",
      diagnostics: [
        {
          severity: "error",
          phase: "layout",
          code: "LUMV_SELECTED_TEXT_OVERFLOW",
          message: "Selected headline text exceeds its frame.",
          subject: {
            kind: "node",
            id: "node_contact_name"
          },
          hint: "Increase the selected text frame height or reduce font size."
        },
        {
          severity: "warning",
          phase: "layout",
          code: "LUMV_UNRELATED_CTA_OVERFLOW",
          message: "CTA text exceeds its frame.",
          subject: {
            kind: "node",
            id: "node_cta_box"
          },
          hint: "Select the CTA layer to review this issue."
        }
      ],
      scene: null,
      preflight: {
        has_errors: true,
        brand_ref_operations: 0,
        token_operations: 0,
        layout_operations: 0
      },
      brand_kit: {
        source: "platform_default",
        id: "brand_kit_platform_default",
        version: 1,
        name: "Platform Default"
      }
    });

    render(<TestEditorApp initialScene={scene} initialSelectedNodeId="node_contact_name" preflightRunner={preflightRunner} />);

    fireEvent.click(screen.getByRole("button", { name: /^Validate$/i }));

    const focused = await screen.findByRole("list", { name: "Focused diagnostics" });
    expect(within(focused).getByText("Artboard A4 Letter")).toBeInTheDocument();
    expect(within(focused).getByText("LUMV_SELECTED_TEXT_OVERFLOW")).toBeInTheDocument();
    expect(within(focused).getByText("Selected headline text exceeds its frame.")).toBeInTheDocument();
    expect(within(focused).queryByText("LUMV_UNRELATED_CTA_OVERFLOW")).not.toBeInTheDocument();

    const additionalDiagnostics = screen.getByRole("list", { name: "Additional diagnostics" });
    expect(within(additionalDiagnostics).getByText("Artboard A4 Letter")).toBeInTheDocument();
    expect(within(additionalDiagnostics).queryByText("LUMV_SELECTED_TEXT_OVERFLOW")).not.toBeInTheDocument();
    expect(within(additionalDiagnostics).getByText("LUMV_UNRELATED_CTA_OVERFLOW")).toBeInTheDocument();
  });

  it("navigates from slot diagnostics to the first bound node", async () => {
    const preflightRunner: EditorPreflightRunner = vi.fn().mockResolvedValue({
      status: "failed",
      diagnostics: [
        {
          severity: "warning",
          phase: "validation",
          code: "LUMS_REQUIRED_SLOT_FIXTURE",
          message: "Slot contact.full_name needs approval fixtures.",
          subject: {
            kind: "slot",
            id: "slot_contact_name"
          },
          hint: "Add samples or worst-case copy in the slot inspector."
        }
      ],
      scene: null,
      preflight: {
        has_errors: true,
        brand_ref_operations: 0,
        token_operations: 0,
        layout_operations: 0
      },
      brand_kit: {
        source: "platform_default",
        id: "brand_kit_platform_default",
        version: 1,
        name: "Platform Default"
      }
    });

    render(<TestEditorApp initialScene={twoPageScene()} initialSelectedNodeId={null} preflightRunner={preflightRunner} />);

    fireEvent.click(screen.getByRole("button", { name: /^Validate$/i }));

    expect((await screen.findAllByText("LUMS_REQUIRED_SLOT_FIXTURE")).length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getAllByRole("button", { name: /show slot slot_contact_name/i })[0]);

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "node_contact_name");
    expect(screen.getByRole("complementary", { name: "Diagnostics sidebar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /diagnostics panel/i })).toHaveAttribute("aria-pressed", "true");
    openInspectorPanel();
    expect(screen.getByRole("heading", { name: "Contact Name" })).toBeInTheDocument();
  });

  it("navigates from page diagnostics to the affected custom page", async () => {
    const scene = twoPageScene();
    scene.pages.page_second.size = {
      width: 600,
      height: 800,
      unit: "px",
      preset: "custom",
      orientation: "portrait"
    };
    const preflightRunner: EditorPreflightRunner = vi.fn().mockResolvedValue({
      status: "failed",
      diagnostics: [
        {
          severity: "error",
          phase: "export",
          code: "LUME_PAGE_SAFE_AREA",
          message: "Second page safe area is missing.",
          subject: {
            kind: "page",
            id: "page_second"
          },
          hint: "Add safe-area metadata before print export."
        }
      ],
      scene: null,
      preflight: {
        has_errors: true,
        brand_ref_operations: 0,
        token_operations: 0,
        layout_operations: 0
      },
      brand_kit: {
        source: "platform_default",
        id: "brand_kit_platform_default",
        version: 1,
        name: "Platform Default"
      }
    });

    render(<TestEditorApp initialScene={scene} initialSelectedNodeId="node_contact_name" preflightRunner={preflightRunner} />);

    fireEvent.click(screen.getByRole("button", { name: /^Validate$/i }));

    expect(await screen.findByText("LUME_PAGE_SAFE_AREA")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /show artboard page_second/i }));

    const canvas = screen.getByTestId("canvas-selection");
    expect(canvas).toHaveAttribute("data-page-width", "600");
    expect(canvas).toHaveAttribute("data-page-height", "800");
    expect(canvas).toHaveAttribute("data-page-unit", "px");
    expect(canvas).toHaveAttribute("data-selected-node", "");
    expect(screen.getByText(/600 x 800 px/)).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Diagnostics sidebar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /diagnostics panel/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("navigates from asset diagnostics to the first node using that asset", async () => {
    const scene = sceneWithAssetNode();
    const preflightRunner: EditorPreflightRunner = vi.fn().mockResolvedValue({
      status: "failed",
      diagnostics: [
        {
          severity: "error",
          phase: "validation",
          code: "LUMA_ASSET_MISSING_BYTES",
          message: "Asset asset_hero is missing preview bytes.",
          subject: {
            kind: "asset",
            id: "asset_hero"
          },
          hint: "Resolve or replace the asset before approval."
        }
      ],
      scene: null,
      preflight: {
        has_errors: true,
        brand_ref_operations: 0,
        token_operations: 0,
        layout_operations: 0
      },
      brand_kit: {
        source: "platform_default",
        id: "brand_kit_platform_default",
        version: 1,
        name: "Platform Default"
      }
    });

    render(<TestEditorApp initialScene={scene} initialSelectedNodeId={null} preflightRunner={preflightRunner} />);

    fireEvent.click(screen.getByRole("button", { name: /^Validate$/i }));

    expect((await screen.findAllByText("LUMA_ASSET_MISSING_BYTES")).length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getAllByRole("button", { name: /show asset asset_hero/i })[0]);

    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "node_hero_image");
    expect(screen.getByRole("complementary", { name: "Diagnostics sidebar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /diagnostics panel/i })).toHaveAttribute("aria-pressed", "true");
    openInspectorPanel();
    expect(screen.getByRole("heading", { name: "Hero Image" })).toBeInTheDocument();
  });

  it("shows structured export failures after successful preflight", async () => {
    const exportRunner: EditorExportRunner = vi.fn().mockResolvedValue({
      status: "failed",
      diagnostics: [
        {
          severity: "error",
          phase: "export",
          code: "LUME0101",
          message: "export request references missing page missing_page",
          subject: {
            kind: "page",
            id: "missing_page"
          },
          hint: "Choose a page that exists in the current scene."
        },
        {
          severity: "warning",
          phase: "export",
          code: "LUME0418",
          message: "Text node overflows the PDF render box.",
          subject: {
            kind: "node",
            id: "node_contact_name"
          },
          hint: "Reduce font size or enlarge the text box before PDF export."
        }
      ],
      artifacts: []
    });

    render(
      <TestEditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        exportRunner={exportRunner}
        preflightRunner={successfulPreflightRunner(twoPageScene())}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /generate preview/i }));

    expect(await screen.findByText("Export failed")).toBeInTheDocument();
    expect(screen.getAllByText("LUME0101").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("export request references missing page missing_page").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("LUME0418").length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getAllByRole("button", { name: /show node node_contact_name/i })[0]);
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "node_contact_name");
    expect(screen.queryByText("Export ready")).not.toBeInTheDocument();
    expect(exportRunner).toHaveBeenCalledWith({
      scene: expect.any(Object),
      pageIds: ["page_a4"],
      profile: expect.objectContaining({
        name: "preview_svg"
      })
    });
  });

  it("saves and removes selected export profiles through canonical operations", () => {
    const scene = twoPageScene();
    scene.export_profiles = [];
    render(<TestEditorApp initialScene={scene} initialSelectedNodeId={null} />);

    expect(screen.getByText("0 document export profiles saved.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /save profile/i }));

    expect(screen.getByText("1 document export profile saved.")).toBeInTheDocument();
    expect(screen.getByText("upsert_export_profile preview_svg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /update saved profile/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove saved/i })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: /remove saved/i }));

    expect(screen.getByText("0 document export profiles saved.")).toBeInTheDocument();
    expect(screen.getByText("remove_export_profile preview_svg")).toBeInTheDocument();
  });

  it("runs injected Brand Kit governance and displays returned diagnostics", async () => {
    const scene = twoPageScene();
    scene.meta.brand_kit = {
      id: "brand_kit_insight_health",
      version: 4
    };
    const brandKit = brandKitSummary();
    const brandGovernanceRunner = vi.fn().mockResolvedValue({
      diagnostics: [
        {
          severity: "error",
          phase: "brand",
          code: "LUMB0807",
          message: "node headline text contrast $text.inverse on $surface.page is 1.00, below required 4.50",
          subject: {
            kind: "node",
            id: "node_contact_name"
          },
          hint: "Use a Brand Kit text token with sufficient contrast."
        }
      ]
    });

    render(
      <TestEditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        initialAvailableBrandKits={[brandKit]}
        brandGovernanceRunner={brandGovernanceRunner}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /brand check/i }));

    expect(await screen.findAllByText("LUMB0807")).toHaveLength(3);
    expect(screen.getAllByText(/text contrast/)).toHaveLength(3);
    fireEvent.click(screen.getAllByRole("button", { name: /show node node_contact_name/i })[0]);
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "node_contact_name");
    expect(brandGovernanceRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        meta: expect.objectContaining({
          brand_kit: {
            id: "brand_kit_insight_health",
            version: 4
          }
        })
      }),
      brandKit
    });
  });

  it("runs injected Brand Kit compatibility against the latest stored version", async () => {
    const scene = twoPageScene();
    scene.meta.brand_kit = {
      id: "brand_kit_insight_health",
      version: 4
    };
    const currentBrandKit = brandKitSummary(4);
    const latestBrandKit = brandKitSummary(5);
    const brandCompatibilityRunner = vi.fn().mockResolvedValue({
      report: {
        from: {
          id: "brand_kit_insight_health",
          version: 4
        },
        to: {
          id: "brand_kit_insight_health",
          version: 5
        },
        status: "migration_required",
        diagnostics: [],
        token_changes: [
          {
            path: "surface.brand",
            kind: "removed",
            from_kind: "color",
            to_kind: null
          }
        ]
      },
      diagnostics: [
        {
          severity: "error",
          phase: "brand",
          code: "LUMB0814",
          message: "color token surface.brand was removed",
          subject: {
            kind: "document"
          },
          hint: "Choose a replacement Brand Kit surface token."
        }
      ]
    });

    render(
      <TestEditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        initialAvailableBrandKits={[currentBrandKit, latestBrandKit]}
        brandCompatibilityRunner={brandCompatibilityRunner}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /compatibility/i }));

    expect(await screen.findByText("Migration required")).toBeInTheDocument();
    expect(screen.getByText("surface.brand removed")).toBeInTheDocument();
    expect(screen.getAllByText("LUMB0814")).toHaveLength(2);
    expect(brandCompatibilityRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        meta: expect.objectContaining({
          brand_kit: {
            id: "brand_kit_insight_health",
            version: 4
          }
        })
      }),
      currentBrandKit,
      targetBrandKit: latestBrandKit
    });
  });
});

function brandKitSummary(version = 4): BrandKitSummary {
  return {
    id: "brand_kit_insight_health",
    version,
    name: "Insight Health",
    approval_status: "generated_unreviewed",
    product_ready: true,
    source: "styles",
    tokens: {
      surface_tokens: ["surface.brand", "surface.card"],
      text_tokens: ["text.primary", "text.inverse"],
      typography_tokens: ["type.headline", "type.body"],
      spacing_tokens: ["space.md", "space.lg"],
      radius_tokens: ["radius.card"],
      opacity_tokens: ["opacity.subtle"]
    },
    authoring_rules: []
  };
}

function successfulPreflightRunner(preflightedScene?: Scene): EditorPreflightRunner {
  return vi.fn(({ scene }) =>
    Promise.resolve({
      status: "applied" as const,
      diagnostics: [],
      scene: JSON.parse(JSON.stringify(preflightedScene ?? scene)) as Scene,
      preflight: {
        has_errors: false,
        brand_ref_operations: 1,
        token_operations: 0,
        layout_operations: 1
      },
      brand_kit: {
        source: "platform_default",
        id: "brand_kit_platform_default",
        version: 1,
        name: "Platform Default"
      }
    })
  );
}

function rectSummary(rect: { x: number; y: number; width: number; height: number }): string {
  return `${rect.x},${rect.y},${rect.width},${rect.height}`;
}

function twoPageScene(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.pages.page_second = {
    ...scene.pages.page_a4,
    id: "page_second",
    name: "Second Page",
    children: []
  };
  return scene;
}

function sceneWithMultiBoundTextSlot(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.nodes.node_contact_secondary = {
    ...JSON.parse(JSON.stringify(scene.nodes.node_contact_name)),
    id: "node_contact_secondary",
    name: "Secondary Contact Name",
    transform: {
      ...scene.nodes.node_contact_name.transform,
      y: scene.nodes.node_contact_name.transform.y + 42
    },
    computed: null,
    children: []
  };
  if (scene.nodes.node_contact_secondary.kind.kind === "text") {
    scene.nodes.node_contact_secondary.kind = {
      ...scene.nodes.node_contact_secondary.kind,
      content: "Original Secondary Contact"
    };
  }
  scene.pages.page_a4.children = ["node_contact_name", "node_contact_secondary"];
  scene.slots.slot_contact_name.bound_nodes = ["node_contact_name", "node_contact_secondary"];
  return scene;
}

function sceneWithTwoLayerNodes(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.nodes.node_cta_box = {
    id: "node_cta_box",
    name: "CTA Box",
    kind: {
      kind: "rect"
    },
    transform: {
      x: 24,
      y: 82,
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
      flip_x: false,
      flip_y: false
    },
    size: {
      width: {
        kind: "fixed",
        value: 120
      },
      height: {
        kind: "fixed",
        value: 36
      }
    },
    children: [],
    fills: [
      {
        id: "paint_cta_fill",
        paint: {
          kind: "solid",
          color: {
            kind: "hex",
            value: "#075e68"
          }
        }
      }
    ],
    strokes: [],
    corner: {
      top_left: 6,
      top_right: 6,
      bottom_right: 6,
      bottom_left: 6
    },
    opacity: 1,
    clip: false,
    layout: null,
    computed: null,
    locked: false
  };
  scene.pages.page_a4.children = ["node_contact_name", "node_cta_box"];
  return scene;
}

function sceneWithAutoLayoutLayers(): Scene {
  const scene = sceneWithTwoLayerNodes();
  scene.nodes.node_stack = {
    ...scene.nodes.node_contact_name,
    id: "node_stack",
    name: "Stack",
    kind: {
      kind: "auto_layout",
      direction: "column",
      wrap: false
    },
    transform: {
      x: 20,
      y: 20,
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
      flip_x: false,
      flip_y: false
    },
    size: {
      width: {
        kind: "fixed",
        value: 260
      },
      height: {
        kind: "fixed",
        value: 180
      }
    },
    children: ["node_contact_name", "node_cta_box"],
    layout: {
      gap: 12,
      padding: [16, 16, 16, 16],
      grow: 0,
      align_x: "start",
      align_y: "start"
    },
    computed: null,
    locked: false
  };
  scene.pages.page_a4.children = ["node_stack"];
  return scene;
}

function sceneWithAssetNode(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.nodes.node_hero_image = {
    ...scene.nodes.node_contact_name,
    id: "node_hero_image",
    name: "Hero Image",
    kind: {
      kind: "image",
      asset_id: "asset_hero",
      alt: "Hero"
    },
    transform: {
      x: 24,
      y: 120,
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
      flip_x: false,
      flip_y: false
    },
    size: {
      width: {
        kind: "fixed",
        value: 320
      },
      height: {
        kind: "fixed",
        value: 180
      }
    },
    children: [],
    source_asset_id: "asset_hero",
    asset_placement: {
      fit: "cover",
      focal_point: null
    }
  };
  scene.pages.page_a4.children = ["node_contact_name", "node_hero_image"];
  return scene;
}
