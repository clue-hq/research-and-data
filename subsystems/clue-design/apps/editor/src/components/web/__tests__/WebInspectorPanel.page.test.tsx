/**
 * F5 task 21 — the dev shell's Page card: the route field the subsystem editor
 * gets for parity with the platform shell.
 *
 * It exists ONLY in the nothing-selected state, because a selected node means
 * the panel is describing that node and the page is not part of it. The two
 * refusals fire no write at all — the assertion that `applyOps` was never
 * called is the real content of those cases.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WebInspectorPanel } from "../WebInspectorPanel";
import { INVALID_ROUTE_MESSAGE, ROUTE_TAKEN_MESSAGE } from "../inspectorPageField";
import type { WebNode, WebOperation, WebPageSummary } from "@/engine/webDocuments";

const HOME: WebPageSummary = {
  id: "home",
  name: "Home",
  route: "/",
  root: "root",
  nodes: { root: { id: "root", kind: "container", classes: "", children: [] } }
};
const PRICING: WebPageSummary = {
  id: "pricing",
  name: "Pricing",
  route: "/pricing",
  root: "root_pricing",
  nodes: { root_pricing: { id: "root_pricing", kind: "container", classes: "", children: [] } }
};

function mountPanel({
  node = null,
  page = HOME,
  pages = [HOME, PRICING],
  applyOps = vi.fn<(operations: WebOperation[], intent?: string) => void>()
}: {
  node?: WebNode | null;
  page?: WebPageSummary | null;
  pages?: WebPageSummary[];
  applyOps?: ReturnType<typeof vi.fn<(operations: WebOperation[], intent?: string) => void>>;
} = {}) {
  render(
    <WebInspectorPanel
      node={node}
      nodeInfo={null}
      pageId={page?.id ?? "home"}
      page={page}
      pages={pages}
      theme={null}
      dialogs={[]}
      previewComponent={vi.fn()}
      selectNode={vi.fn()}
      onReplaceImage={vi.fn()}
      onChooseBackground={vi.fn()}
      editingNodeId={null}
      richTextFormats={null}
      formatRichText={vi.fn()}
      customComponentArtifact={null}
      customComponentArtifactStatus="idle"
      customComponentArtifactError={null}
      customComponentRuntime={null}
      customComponentRepublishRequired={false}
      onEditCustomComponentWithAI={vi.fn()}
      onRepublish={vi.fn()}
      fragmentCard={null}
      fragmentCardStatus="idle"
      fragmentCardError={null}
      dormantSections={[]}
      documentAssets={[]}
      onGenerateFragmentPreview={vi.fn()}
      onActivateFragment={vi.fn()}
      onRetireFragment={vi.fn()}
      fragmentActionBusy={false}
      fragmentActionError={null}
      applyOps={applyOps}
      busy={false}
      note={null}
      error={null}
    />
  );
  return applyOps;
}

function typeRoute(value: string) {
  const field = screen.getByLabelText("Page route") as HTMLInputElement;
  fireEvent.change(field, { target: { value } });
  fireEvent.blur(field);
  return field;
}

describe("the inspector's Page card", () => {
  it("commits a new route as one set_page_meta op", () => {
    const applyOps = mountPanel();
    typeRoute("/home-2026");
    expect(applyOps).toHaveBeenCalledTimes(1);
    expect(applyOps.mock.calls[0][0]).toEqual([
      { kind: "set_page_meta", page_id: "home", route: "/home-2026" }
    ]);
  });

  it("commits on Enter as well as blur", () => {
    const applyOps = mountPanel();
    const field = screen.getByLabelText("Page route") as HTMLInputElement;
    field.focus();
    fireEvent.change(field, { target: { value: "/home-2026" } });
    // Enter blurs the field, which is what commits — the shape every other text
    // field in this panel already uses.
    fireEvent.keyDown(field, { key: "Enter" });
    expect(applyOps).toHaveBeenCalledTimes(1);
  });

  it("writes nothing when the route is unchanged", () => {
    const applyOps = mountPanel();
    typeRoute("/");
    expect(applyOps).not.toHaveBeenCalled();
  });

  it("refuses an ungrammatical route and fires no write", () => {
    const applyOps = mountPanel();
    typeRoute("/Pricing");
    expect(applyOps).not.toHaveBeenCalled();
    expect(screen.getByText(INVALID_ROUTE_MESSAGE)).toBeTruthy();
  });

  it("refuses a route another page already holds and fires no write", () => {
    const applyOps = mountPanel();
    typeRoute("/pricing");
    expect(applyOps).not.toHaveBeenCalled();
    expect(screen.getByText(ROUTE_TAKEN_MESSAGE)).toBeTruthy();
  });

  it("is absent while a node is selected", () => {
    mountPanel({
      node: { id: "root", kind: "container", classes: "", children: [] }
    });
    expect(screen.queryByLabelText("Page route")).toBeNull();
  });

  it("is absent when the document has no page to describe", () => {
    mountPanel({ page: null, pages: [] });
    expect(screen.queryByLabelText("Page route")).toBeNull();
  });
});
