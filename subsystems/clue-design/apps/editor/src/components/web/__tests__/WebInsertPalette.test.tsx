import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WebInsertPalette } from "../WebInsertPalette";
import type { CustomComponentCatalogItem } from "@/engine/webDocuments";

const COMPONENT: CustomComponentCatalogItem = {
  accountId: "acc_alpha",
  slug: "pricing-card",
  sourceVersion: 3,
  artifactCount: 2,
  latestArtifact: {
    artifact_id: `ccart_${"a".repeat(64)}`,
    account_id: "acc_alpha",
    slug: "pricing-card",
    manifest: {
      schema_version: 2,
      meta: {
        name: "Pricing Card",
        description: "A compact pricing callout."
      },
      props_schema: {
        type: "object",
        properties: {},
        additionalProperties: false
      },
      defaults: {},
      warnings: [],
      browser: { format: "esm", react: "host-singleton" }
    },
    provenance: { source_version: 3 }
  }
};

function renderPalette(overrides: Partial<React.ComponentProps<typeof WebInsertPalette>> = {}) {
  const onInsertCustomComponent = vi.fn();
  render(
    <WebInsertPalette
      onInsert={vi.fn()}
      onInsertImage={vi.fn()}
      onInsertCustomComponent={onInsertCustomComponent}
      customComponents={[COMPONENT]}
      customComponentsStatus="ready"
      customComponentsUnavailableReason={null}
      disabled={false}
      {...overrides}
    />
  );
  return { onInsertCustomComponent };
}

describe("WebInsertPalette custom components", () => {
  it("announces and inserts a named compiled component", () => {
    const { onInsertCustomComponent } = renderPalette();
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    const item = screen.getByRole("menuitem", {
      name: "Insert Pricing Card custom component"
    });
    expect(item).toHaveTextContent("A compact pricing callout.");
    fireEvent.click(item);
    expect(onInsertCustomComponent).toHaveBeenCalledWith(COMPONENT);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("explains why account-free documents cannot use the registry", () => {
    renderPalette({
      customComponents: [],
      customComponentsStatus: "idle",
      customComponentsUnavailableReason:
        "Assign this website to an account to use custom components."
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(
      screen.getByText("Assign this website to an account to use custom components.")
    ).toBeInTheDocument();
  });
});
