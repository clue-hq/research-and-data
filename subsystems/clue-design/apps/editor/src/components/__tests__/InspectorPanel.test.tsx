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
});
