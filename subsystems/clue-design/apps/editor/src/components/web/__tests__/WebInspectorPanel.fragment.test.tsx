/**
 * What the inspector PANEL chooses for a cloned section (clone-fidelity F3.2, D-F3).
 *
 * `WebFragmentInspector.test.tsx` tests the card in isolation and therefore structurally cannot
 * observe which cards the panel picked — which left D-F3's central structural guarantee untested
 * while its docstring claimed to pin it (review finding I-5). This file mounts the panel itself.
 *
 * The guarantee: a fragment gets its own body and NONE of the generic cards. That is not tidiness.
 * The CSS-classes escape hatch is where somebody writes `h-[3000px]` onto a frozen harvested band
 * — the manual resize founder ruling D-F3 forbids outright — and the spacing card re-lays-out
 * somebody else's section from the outside. A one-line change to the early return in
 * `WebInspectorBody` reopens that hole silently, and this is the test that goes red when it does.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WebInspectorPanel } from "../WebInspectorPanel";
import type { WebNode, WebPageSummary } from "@/engine/webDocuments";
import type { FragmentCard } from "@/engine/webFragmentCards";

const FRAGMENT_ID = "frag_0123456789abcdef";

const FRAGMENT: WebNode = {
  id: "frg_hero",
  kind: "fragment",
  classes: "w-full py-12",
  fragment_id: FRAGMENT_ID,
  slots: {}
};

const CONTAINER: WebNode = { id: "sec_a", kind: "container", classes: "py-12", children: [] };

const PAGE = {
  id: "home",
  name: "Home",
  route: "/",
  root: "root",
  nodes: {
    root: { id: "root", kind: "container", classes: "", children: ["frg_hero"] },
    frg_hero: FRAGMENT
  }
} as unknown as WebPageSummary;

const CARD: FragmentCard = {
  fragmentId: FRAGMENT_ID,
  label: "Products",
  sectionRole: "other",
  status: "approved",
  pageUrl: "https://insight.example/",
  sectionIndex: 4,
  previewPath: null,
  previewBasis: null,
  slots: [{ key: "headline", kind: "text", fallback: "Products" }],
  degraded: false,
  degradedReason: null,
  degradedNote: null,
  derivedFrom: null,
  derivedReason: null,
  repairsWhat: null,
  supersededBy: null,
  lineageAmbiguous: [],
  lineageRoot: FRAGMENT_ID,
  family: [],
  hiddenOnSource: null,
  activation: { allowed: false, reason: "not_dormant", message: null },
  retirement: { allowed: false, reason: "not_a_repair", message: null }
};

function mountPanel(node: WebNode) {
  render(
    <WebInspectorPanel
      node={node}
      nodeInfo={null}
      pageId="home"
      page={PAGE}
      pages={[PAGE]}
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
      fragmentCard={node.kind === "fragment" ? CARD : null}
      fragmentCardStatus={node.kind === "fragment" ? "ready" : "idle"}
      fragmentCardError={null}
      dormantSections={[]}
      documentAssets={[]}
      onGenerateFragmentPreview={vi.fn()}
      onActivateFragment={vi.fn()}
      onRetireFragment={vi.fn()}
      fragmentActionBusy={false}
      fragmentActionError={null}
      applyOps={vi.fn()}
      busy={false}
      note={null}
      error={null}
    />
  );
}

describe("the inspector panel on a cloned section", () => {
  it("offers no CSS-class escape hatch and no spacing control (D-F3)", () => {
    mountPanel(FRAGMENT);
    // The clone's own editing surface IS there…
    expect(screen.getByText("Cloned section")).toBeTruthy();
    expect(screen.getByText("Section content")).toBeTruthy();
    // …and the two controls that would hand-resize or re-lay-out a frozen band are not.
    expect(screen.queryByLabelText("CSS classes")).toBeNull();
    expect(screen.queryByText("CSS classes")).toBeNull();
    expect(screen.queryByText("Spacing")).toBeNull();
    expect(screen.queryByText("Personalization")).toBeNull();
  });

  it("still offers both to an ordinary node, so the absence above is about the kind", () => {
    mountPanel(CONTAINER);
    expect(screen.getByLabelText("CSS classes")).toBeTruthy();
    expect(screen.getByText("Spacing")).toBeTruthy();
    // …and the cloned-section body is not offered to something that is not a clone.
    expect(screen.queryByText("Cloned section")).toBeNull();
  });
});
