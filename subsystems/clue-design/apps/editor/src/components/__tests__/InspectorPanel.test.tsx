import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
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
});
