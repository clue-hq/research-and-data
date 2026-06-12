import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Diagnostic, Scene } from "@/engine/contracts";
import { InspectorPanel } from "../InspectorPanel";

describe("InspectorPanel", () => {
  it("shows selected node and bound slot metadata", () => {
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: minimalScene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        onOperation: vi.fn()
      })
    );

    expect(screen.getByText("Contact Name")).toBeInTheDocument();
    expect(screen.getByDisplayValue("contact.full_name")).toBeInTheDocument();
    expect(screen.getByLabelText("Slot summary")).toBeInTheDocument();
    expect(screen.getByText("Document")).toBeInTheDocument();
    expect(screen.getByText("Shrink font 12-18")).toBeInTheDocument();
    expect(screen.getAllByText("Dr. Priya Sharma").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Dr. Maximilian Alexander Whitmore").length).toBeGreaterThan(0);
    expect(screen.getByText(/A4 Letter/)).toBeInTheDocument();
    expect(screen.getByText(/Contact Name \(node_contact_name\)/)).toBeInTheDocument();
    expect(screen.getByLabelText("Slot constraints")).toBeInTheDocument();
    expect(screen.getAllByText("80").length).toBeGreaterThan(0);
  });

  it("emits an upsert slot operation when slot metadata changes", () => {
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: minimalScene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        onOperation
      })
    );

    fireEvent.change(screen.getByDisplayValue("Contact full name"), {
      target: {
        value: "Recipient name"
      }
    });

    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "upsert_slot",
        slot: expect.objectContaining({
          id: "slot_contact_name",
          key: "contact.full_name",
          label: "Recipient name"
        })
      })
    );
  });

  it("emits slot approval fixture updates through upsert slot operations", () => {
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: minimalScene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        onOperation
      })
    );

    fireEvent.change(screen.getByLabelText("Sample fixtures"), {
      target: {
        value: "Dr. Asha Rao\nDr. Jonathan Verylongname"
      }
    });
    fireEvent.change(screen.getByLabelText("Worst-case fixture"), {
      target: {
        value: "Dr. Maximilian Alexander Whitmore-Singh"
      }
    });
    fireEvent.change(screen.getByLabelText("Fixture Max Length"), {
      target: {
        value: "96"
      }
    });
    fireEvent.change(screen.getByLabelText("Formatting Max Length"), {
      target: {
        value: "72"
      }
    });

    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "upsert_slot",
        slot: expect.objectContaining({
          id: "slot_contact_name",
          validation: expect.objectContaining({
            samples: ["Dr. Asha Rao", "Dr. Jonathan Verylongname"]
          })
        })
      })
    );
    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "upsert_slot",
        slot: expect.objectContaining({
          id: "slot_contact_name",
          validation: expect.objectContaining({
            worst_case: "Dr. Maximilian Alexander Whitmore-Singh"
          })
        })
      })
    );
    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "upsert_slot",
        slot: expect.objectContaining({
          id: "slot_contact_name",
          validation: expect.objectContaining({
            max_length: 96
          })
        })
      })
    );
    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "upsert_slot",
        slot: expect.objectContaining({
          id: "slot_contact_name",
          formatting: expect.objectContaining({
            max_length: 72
          })
        })
      })
    );
  });

  it("applies slot preview fixtures to bound text nodes through canonical update operations", () => {
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: minimalScene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        onOperation
      })
    );

    fireEvent.click(screen.getAllByRole("button", { name: "Apply to text node" })[1]);

    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "node_contact_name",
        patch: expect.objectContaining({
          kind: {
            kind: "set",
            value: expect.objectContaining({
              content: "Dr. Maximilian Alexander Whitmore"
            })
          }
        })
      })
    );
  });

  it("emits text style token updates from the token picker", () => {
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: minimalScene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        brandTokens: {
          typography_tokens: ["type.headline", "type.body"],
          radius_tokens: ["radius.card"],
          opacity_tokens: ["opacity.subtle"]
        },
        onOperation
      })
    );

    fireEvent.change(screen.getByLabelText("Style Token"), {
      target: {
        value: "type.headline"
      }
    });

    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "node_contact_name",
        patch: expect.objectContaining({
          kind: expect.objectContaining({
            kind: "set",
            value: expect.objectContaining({
              style_token: "type.headline"
            })
          })
        })
      })
    );
  });

  it("emits page background token updates from the page inspector", () => {
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: null,
        selectedNodeId: null,
        brandTokens: {
          surface_tokens: ["surface.page", "surface.card"]
        },
        onOperation
      })
    );

    fireEvent.change(screen.getByLabelText("Page Fill Token"), {
      target: {
        value: "surface.card"
      }
    });

    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "update_page",
        page_id: "page_a4",
        patch: expect.objectContaining({
          background: expect.objectContaining({
            kind: "set",
            value: [
              expect.objectContaining({
                paint: {
                  kind: "token",
                  token: "surface.card"
                }
              })
            ]
          })
        })
      })
    );
  });

  it("emits page rename operations from the page inspector", () => {
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: null,
        selectedNodeId: null,
        onOperation
      })
    );

    fireEvent.change(screen.getByLabelText("Name"), {
      target: {
        value: "Client Square Ad"
      }
    });

    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "update_page",
        page_id: "page_a4",
        patch: expect.objectContaining({
          name: {
            kind: "set",
            value: "Client Square Ad"
          }
        })
      })
    );
  });

  it("emits node rename operations from the node inspector", () => {
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: minimalScene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        onOperation
      })
    );

    fireEvent.change(screen.getByLabelText("Name"), {
      target: {
        value: "Personalized Headline"
      }
    });

    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "node_contact_name",
        patch: expect.objectContaining({
          name: {
            kind: "set",
            value: "Personalized Headline"
          }
        })
      })
    );
  });

  it("emits selected node removal through the inspector delete button", () => {
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: minimalScene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        onOperation
      })
    );

    fireEvent.click(screen.getByRole("button", { name: /delete/i }));

    expect(onOperation).toHaveBeenCalledWith({
      kind: "remove_node",
      node_id: "node_contact_name"
    });
  });

  it("disables selected node deletion for locked nodes", () => {
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    scene.nodes.node_contact_name.locked = true;

    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        onOperation: vi.fn()
      })
    );

    expect(screen.getByRole("button", { name: /delete/i })).toBeDisabled();
  });

  it("emits document metadata operations from the document inspector", () => {
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: null,
        selectedNodeId: null,
        onOperation
      })
    );

    fireEvent.change(screen.getByLabelText("Document Title"), {
      target: {
        value: "Neurosurgery LinkedIn Ad"
      }
    });
    fireEvent.change(screen.getByLabelText("Artifact Type"), {
      target: {
        value: "linkedin_ad"
      }
    });

    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "update_document",
        patch: expect.objectContaining({
          title: {
            kind: "set",
            value: "Neurosurgery LinkedIn Ad"
          }
        })
      })
    );
    expect(onOperation).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "update_document",
        patch: expect.objectContaining({
          artifact_type: {
            kind: "set",
            value: "linkedin_ad"
          }
        })
      })
    );
  });

  it("shows a page-level slot overview grouped by bound nodes", () => {
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: null,
        selectedNodeId: null,
        onOperation: vi.fn()
      })
    );

    expect(screen.getByLabelText("Page slot overview")).toBeInTheDocument();
    expect(screen.getByText("contact.full_name")).toBeInTheDocument();
    expect(screen.getByText(/Required · text_short · Shrink font 12-18/)).toBeInTheDocument();
    expect(screen.getByText(/Preview Placeholder: Dr. Priya Sharma/)).toBeInTheDocument();
    expect(screen.getByText(/A4 Letter \/ Contact Name \(node_contact_name\)/)).toBeInTheDocument();
  });

  it("surfaces unbound required slots in the page-level slot overview", () => {
    const scene = unboundRequiredSlotScene();
    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: null,
        selectedNodeId: null,
        onOperation: vi.fn()
      })
    );

    expect(screen.getByText("campaign.cta")).toBeInTheDocument();
    expect(screen.getByText("SLOT_REQUIRED_UNBOUND")).toBeInTheDocument();
    expect(screen.getByText("SLOT_REQUIRED_NO_FIXTURE")).toBeInTheDocument();
  });

  it("surfaces slot readiness issues for selected semantic slots", () => {
    const scene = slotReadinessScene();
    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        onOperation: vi.fn()
      })
    );

    const readiness = within(screen.getByLabelText("Slot readiness"));

    expect(readiness.getByText("SLOT_SCOPE_MISSING")).toBeInTheDocument();
    expect(readiness.getByText("SLOT_IMAGE_NODE_KIND")).toBeInTheDocument();
    expect(readiness.getByText("SLOT_REQUIRED_NO_FIXTURE")).toBeInTheDocument();
    expect(readiness.getByText("SLOT_OVERFLOW_CLIPS")).toBeInTheDocument();
    expect(readiness.getByText(/expects image\/logo content but is bound to text/)).toBeInTheDocument();
  });

  it("flags slot approval fixtures that exceed configured max length", () => {
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    scene.slots.slot_contact_name = {
      ...scene.slots.slot_contact_name,
      formatting: {
        ...scene.slots.slot_contact_name.formatting,
        max_length: 12
      },
      validation: {
        ...scene.slots.slot_contact_name.validation,
        samples: ["Dr. Extremely Long Personalization Name"]
      }
    };

    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        onOperation: vi.fn()
      })
    );

    const readiness = within(screen.getByLabelText("Slot readiness"));

    expect(readiness.getAllByText("SLOT_FIXTURE_EXCEEDS_MAX_LENGTH")).toHaveLength(2);
    expect(readiness.getByText(/Placeholder fixture for contact.full_name is 16 characters/)).toBeInTheDocument();
    expect(readiness.getByText(/Sample fixture for contact.full_name is 39 characters/)).toBeInTheDocument();
  });

  it("emits fill, stroke, and stroke-width token updates", () => {
    const scene = nodeWithStrokeScene();
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        brandTokens: {
          text_tokens: ["text.primary", "text.inverse"],
          border_tokens: ["border.default"],
          stroke_width_tokens: ["stroke.width.thin"],
          typography_tokens: ["type.headline"],
          radius_tokens: ["radius.card"],
          opacity_tokens: ["opacity.subtle"]
        },
        onOperation
      })
    );

    fireEvent.change(screen.getByLabelText("Fill Token"), {
      target: {
        value: "text.primary"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "node_contact_name",
        patch: expect.objectContaining({
          fills: expect.objectContaining({
            kind: "set",
            value: [
              expect.objectContaining({
                paint: {
                  kind: "token",
                  token: "text.primary"
                }
              })
            ]
          })
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Stroke Token"), {
      target: {
        value: "border.default"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "node_contact_name",
        patch: expect.objectContaining({
          strokes: expect.objectContaining({
            kind: "set",
            value: [
              expect.objectContaining({
                paint: {
                  kind: "token",
                  token: "border.default"
                },
                width: 1.5
              })
            ]
          })
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Stroke Width Token"), {
      target: {
        value: "stroke.width.thin"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "node_contact_name",
        patch: expect.objectContaining({
          strokes: expect.objectContaining({
            kind: "set",
            value: [
              expect.objectContaining({
                width_token: "stroke.width.thin"
              })
            ]
          })
        })
      })
    );
  });

  it("emits raw fill, stroke, and stroke-width style updates", () => {
    const scene = nodeWithStrokeScene();
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        onOperation
      })
    );

    fireEvent.change(screen.getByLabelText("Fill Color"), {
      target: {
        value: "#ff0000"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "node_contact_name",
        patch: expect.objectContaining({
          fills: expect.objectContaining({
            kind: "set",
            value: [
              expect.objectContaining({
                paint: {
                  kind: "solid",
                  color: {
                    kind: "hex",
                    value: "#ff0000"
                  }
                }
              })
            ]
          })
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Stroke Color"), {
      target: {
        value: "#00ff00"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "node_contact_name",
        patch: expect.objectContaining({
          strokes: expect.objectContaining({
            kind: "set",
            value: [
              expect.objectContaining({
                width: 1.5,
                width_token: null,
                paint: {
                  kind: "solid",
                  color: {
                    kind: "hex",
                    value: "#00ff00"
                  }
                }
              })
            ]
          })
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Stroke Width"), {
      target: {
        value: "2.25"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "node_contact_name",
        patch: expect.objectContaining({
          strokes: expect.objectContaining({
            kind: "set",
            value: [
              expect.objectContaining({
                width: 2.25,
                width_token: null
              })
            ]
          })
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Radius All"), {
      target: {
        value: "14"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "node_contact_name",
        patch: expect.objectContaining({
          corner: {
            kind: "set",
            value: {
              top_left: 14,
              top_right: 14,
              bottom_right: 14,
              bottom_left: 14,
              token: null
            }
          }
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Radius TL"), {
      target: {
        value: "4"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "node_contact_name",
        patch: expect.objectContaining({
          corner: {
            kind: "set",
            value: expect.objectContaining({
              top_left: 4,
              top_right: scene.nodes.node_contact_name.corner.top_right,
              bottom_right: scene.nodes.node_contact_name.corner.bottom_right,
              bottom_left: scene.nodes.node_contact_name.corner.bottom_left,
              token: null
            })
          }
        })
      })
    );
  });

  it("labels selected style fields as token-backed, raw, or missing from the current Brand Kit", () => {
    const scene = nodeWithStrokeScene();
    scene.nodes.node_contact_name.fills = [
      {
        id: "paint_contact_fill",
        paint: {
          kind: "token",
          token: "text.primary"
        }
      }
    ];
    scene.nodes.node_contact_name.corner = {
      ...scene.nodes.node_contact_name.corner,
      token: "radius.legacy"
    };
    if (scene.nodes.node_contact_name.kind.kind === "text") {
      scene.nodes.node_contact_name.kind = {
        ...scene.nodes.node_contact_name.kind,
        style_token: "type.headline"
      };
    }

    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        brandTokens: {
          text_tokens: ["text.primary"],
          border_tokens: ["border.default"],
          typography_tokens: ["type.headline"],
          radius_tokens: ["radius.card"],
          opacity_tokens: ["opacity.subtle"]
        },
        onOperation: vi.fn()
      })
    );

    const summary = within(screen.getByLabelText("Selected style summary"));

    expect(summary.getByText("$text.primary")).toBeInTheDocument();
    expect(summary.getByText("#123456 / 1.5")).toBeInTheDocument();
    expect(summary.getByText("$radius.legacy (not in current Brand Kit)")).toBeInTheDocument();
    expect(summary.getByText("$type.headline")).toBeInTheDocument();
    expect(summary.getAllByText("Token").length).toBeGreaterThanOrEqual(2);
    expect(summary.getAllByText("Raw").length).toBeGreaterThanOrEqual(1);
    expect(summary.getByText("Missing token")).toBeInTheDocument();
  });

  it("emits container auto-layout direction, wrap, grow, padding, and alignment operations", () => {
    const scene = autoLayoutScene();
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.stack,
        selectedNodeId: "stack",
        onOperation
      })
    );

    fireEvent.change(screen.getByLabelText("Direction"), {
      target: {
        value: "row"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "stack",
        patch: expect.objectContaining({
          kind: expect.objectContaining({
            kind: "set",
            value: expect.objectContaining({
              kind: "auto_layout",
              direction: "row"
            })
          })
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Wrap"), {
      target: {
        value: "true"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "stack",
        patch: expect.objectContaining({
          kind: expect.objectContaining({
            value: expect.objectContaining({
              wrap: true
            })
          })
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Grow"), {
      target: {
        value: "1"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "stack",
        patch: expect.objectContaining({
          layout: expect.objectContaining({
            value: expect.objectContaining({
              grow: 1
            })
          })
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Pad R"), {
      target: {
        value: "18"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "stack",
        patch: expect.objectContaining({
          layout: expect.objectContaining({
            value: expect.objectContaining({
              padding: [12, 18, 12, 12]
            })
          })
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Align X"), {
      target: {
        value: "center"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "stack",
        patch: expect.objectContaining({
          layout: expect.objectContaining({
            value: expect.objectContaining({
              align_x: "center",
              align_y: "start"
            })
          })
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Align Y"), {
      target: {
        value: "end"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "stack",
        patch: expect.objectContaining({
          layout: expect.objectContaining({
            value: expect.objectContaining({
              align_x: "start",
              align_y: "end"
            })
          })
        })
      })
    );
  });

  it("shows selected container diagnostics for descendant layout issues", () => {
    const scene = autoLayoutScene();
    const onSelectSubject = vi.fn();
    const diagnostics: Diagnostic[] = [
      {
        severity: "error",
        phase: "layout",
        code: "LUMV_TEXT_OVERFLOW",
        message: "Stack child text overflows its computed layout bounds.",
        subject: {
          kind: "node",
          id: "stack_child"
        },
        hint: "Reduce copy, shrink the type, or enlarge the auto-layout container."
      },
      {
        severity: "warning",
        phase: "export",
        code: "LUME_PRINT_FONT_EMBEDDING",
        message: "PDF font embedding is not available yet.",
        subject: {
          kind: "document"
        },
        hint: null
      }
    ];
    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.stack,
        selectedNodeId: "stack",
        diagnostics,
        onOperation: vi.fn(),
        onSelectSubject
      })
    );

    const selectedIssues = within(screen.getByLabelText("Selected Issues"));

    expect(selectedIssues.getByText("LUMV_TEXT_OVERFLOW")).toBeInTheDocument();
    expect(selectedIssues.getByText("Stack child text overflows its computed layout bounds.")).toBeInTheDocument();
    expect(selectedIssues.queryByText("LUME_PRINT_FONT_EMBEDDING")).not.toBeInTheDocument();

    fireEvent.click(selectedIssues.getByRole("button", { name: /show node stack_child/i }));
    expect(onSelectSubject).toHaveBeenCalledWith({
      kind: "node",
      id: "stack_child"
    });
  });

  it("shows page diagnostics while inspecting the active artboard", () => {
    const diagnostics: Diagnostic[] = [
      {
        severity: "warning",
        phase: "layout",
        code: "LUMV_SAFE_AREA",
        message: "Headline is outside the active page safe area.",
        subject: {
          kind: "node",
          id: "node_contact_name"
        },
        hint: "Move the text into the safe area before export."
      },
      {
        severity: "error",
        phase: "layout",
        code: "LUMV_OTHER_PAGE",
        message: "Another page has a layout issue.",
        subject: {
          kind: "page",
          id: "missing_page"
        },
        hint: null
      }
    ];
    render(
      React.createElement(InspectorPanel, {
        scene: minimalScene,
        activePage: minimalScene.pages.page_a4,
        selectedNode: null,
        selectedNodeId: null,
        diagnostics,
        onOperation: vi.fn()
      })
    );

    const pageIssues = within(screen.getByLabelText("Page Issues"));

    expect(pageIssues.getByText("LUMV_SAFE_AREA")).toBeInTheDocument();
    expect(pageIssues.getByText("Headline is outside the active page safe area.")).toBeInTheDocument();
    expect(pageIssues.queryByText("LUMV_OTHER_PAGE")).not.toBeInTheDocument();
  });

  it("marks auto-layout children as managed and disables direct geometry fields", () => {
    const scene = autoLayoutScene();
    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.stack_child,
        selectedNodeId: "stack_child",
        onOperation: vi.fn()
      })
    );

    expect(screen.getByText(/managed by an auto-layout parent/)).toBeInTheDocument();
    expect(screen.getAllByLabelText("X")[0]).toBeDisabled();
    expect(screen.getAllByLabelText("Y")[0]).toBeDisabled();
    expect(screen.getByLabelText("W")).toBeDisabled();
    expect(screen.getByLabelText("H")).toBeDisabled();
    expect(screen.getByLabelText("Grow")).toBeInTheDocument();
  });

  it("emits sizing-mode operations for auto-layout managed children", () => {
    const scene = autoLayoutScene();
    const onOperation = vi.fn();
    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.stack_child,
        selectedNodeId: "stack_child",
        onOperation
      })
    );

    expect(screen.getAllByLabelText("X")[0]).toBeDisabled();
    expect(screen.getByLabelText("Width mode")).toBeEnabled();
    expect(screen.getByLabelText("Height mode")).toBeEnabled();

    fireEvent.change(screen.getByLabelText("Width mode"), {
      target: {
        value: "fill"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "stack_child",
        patch: expect.objectContaining({
          size: expect.objectContaining({
            kind: "set",
            value: expect.objectContaining({
              width: {
                kind: "fill",
                value: {
                  weight: 1
                }
              }
            })
          })
        })
      })
    );

    fireEvent.change(screen.getByLabelText("Height mode"), {
      target: {
        value: "hug"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "stack_child",
        patch: expect.objectContaining({
          size: expect.objectContaining({
            value: expect.objectContaining({
              height: {
                kind: "hug"
              }
            })
          })
        })
      })
    );
  });

  it("edits fill weights through canonical size patches", () => {
    const scene = autoLayoutScene();
    scene.nodes.stack_child.size = {
      ...scene.nodes.stack_child.size,
      width: {
        kind: "fill",
        value: {
          weight: 1
        }
      }
    };
    const onOperation = vi.fn();

    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.stack_child,
        selectedNodeId: "stack_child",
        onOperation
      })
    );

    fireEvent.change(screen.getByLabelText("Width fill weight"), {
      target: {
        value: "2"
      }
    });

    expect(onOperation).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "update_node",
        node_id: "stack_child",
        patch: expect.objectContaining({
          size: expect.objectContaining({
            value: expect.objectContaining({
              width: {
                kind: "fill",
                value: {
                  weight: 2
                }
              }
            })
          })
        })
      })
    );
  });

  it("disables direct geometry controls for locked nodes", () => {
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    scene.nodes.node_contact_name.locked = true;

    render(
      React.createElement(InspectorPanel, {
        scene,
        activePage: scene.pages.page_a4,
        selectedNode: scene.nodes.node_contact_name,
        selectedNodeId: "node_contact_name",
        onOperation: vi.fn()
      })
    );

    expect(screen.getByText(/Unlock it before moving, resizing, or rotating it/)).toBeInTheDocument();
    expect(screen.getAllByLabelText("X")[0]).toBeDisabled();
    expect(screen.getAllByLabelText("Y")[0]).toBeDisabled();
    expect(screen.getByLabelText("W")).toBeDisabled();
    expect(screen.getByLabelText("H")).toBeDisabled();
    expect(screen.getByLabelText("Rotate")).toBeDisabled();
    expect(screen.getByLabelText("Opacity")).toBeDisabled();
    expect(screen.getByLabelText("Fill Color")).toBeDisabled();
    expect(screen.getByLabelText("Stroke Color")).toBeDisabled();
    expect(screen.getByLabelText("Stroke Width")).toBeDisabled();
    expect(screen.getByLabelText("Radius All")).toBeDisabled();
    expect(screen.getByLabelText("Radius TL")).toBeDisabled();
    expect(screen.getByLabelText("Content")).toBeDisabled();
    expect(screen.getByLabelText("Family")).toBeDisabled();
    expect(screen.getByLabelText("Size")).toBeDisabled();
    expect(screen.getByLabelText("Weight")).toBeDisabled();
    expect(screen.getByLabelText("Align")).toBeDisabled();
    expect(screen.getByLabelText("Line Height")).toBeDisabled();
    expect(screen.getByLabelText("Letter Spacing")).toBeDisabled();
    expect(screen.getByLabelText("Max Lines")).toBeDisabled();
    expect(screen.getByLabelText("Wrap")).toBeDisabled();
    expect(screen.getByLabelText("Direction")).toBeDisabled();
  });
});

function nodeWithStrokeScene(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.nodes.node_contact_name.strokes = [
    {
      id: "paint_contact_stroke",
      paint: {
        kind: "solid",
        color: {
          kind: "hex",
          value: "#123456"
        }
      },
      width: 1.5,
      width_token: null
    }
  ];
  return scene;
}

function autoLayoutScene(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.pages.page_a4.children = ["stack"];
  scene.nodes.stack = {
    ...scene.nodes.node_contact_name,
    id: "stack",
    name: "Stack",
    kind: {
      kind: "auto_layout",
      direction: "column",
      wrap: false
    },
    children: ["stack_child"],
    layout: {
      gap: 8,
      padding: [12, 12, 12, 12],
      grow: 0,
      align_x: "start",
      align_y: "start"
    }
  };
  scene.nodes.stack_child = {
    ...scene.nodes.node_contact_name,
    id: "stack_child",
    name: "Stack Child",
    children: [],
    layout: null
  };
  return scene;
}

function slotReadinessScene(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.slots = {
    slot_account_logo: {
      ...scene.slots.slot_contact_name,
      id: "slot_account_logo",
      key: "account.logo",
      label: "Account logo",
      content_type: "logo",
      scope: {
        kind: "page",
        id: "missing_page"
      },
      bound_nodes: ["node_contact_name"],
      required: true,
      placeholder: null,
      overflow: {
        kind: "clip"
      },
      validation: {
        samples: [],
        worst_case: null,
        max_length: null
      },
      image_policy: {
        fit: "contain",
        focal_point: null,
        min_dpi: 300,
        preserve_transparency: true,
        aspect_ratio: null
      }
    }
  };
  return scene;
}

function unboundRequiredSlotScene(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.slots.slot_campaign_cta = {
    ...scene.slots.slot_contact_name,
    id: "slot_campaign_cta",
    key: "campaign.cta",
    label: "Campaign CTA",
    bound_nodes: [],
    required: true,
    placeholder: null,
    validation: {
      samples: [],
      worst_case: null,
      max_length: null
    }
  };
  return scene;
}
