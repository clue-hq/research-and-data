/**
 * The cloned-section inspector card (clone-fidelity F3.2).
 *
 * What a human may do to a clone is narrower than for any other node, and this file pins the
 * narrowness as much as the affordances:
 *
 * * **D-F3 / R1** — slot VALUES only. One control per slot kind, every one of them building the
 *   same whole-props write, and NO class escape hatch or spacing card (which is how a frozen
 *   band would otherwise be resized or re-laid-out by hand).
 * * **D-F6** — a broken clone shows its marker and what the reason means; a repair says which
 *   clone it repairs; a repair can be retired and the harvested ORIGINAL never can (R17-3).
 * * **D-F8** — a hidden-on-source section says so, shows its evidence, and offers the picture
 *   before the decision (P-7's isolation render), never the decision alone.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WebDormantSectionsCard, WebFragmentInspector } from "../WebFragmentInspector";
import type { FragmentCard } from "@/engine/webFragmentCards";
import type { WebNode } from "@/engine/webDocuments";

const FRAGMENT_ID = "frag_0123456789abcdef";

const NODE: WebNode = {
  id: "frg_hero",
  kind: "fragment",
  classes: "",
  fragment_id: FRAGMENT_ID,
  slots: {}
};

function card(overrides: Partial<FragmentCard> = {}): FragmentCard {
  return {
    fragmentId: FRAGMENT_ID,
    label: "Products",
    sectionRole: "other",
    status: "approved",
    pageUrl: "https://insight.example/",
    sectionIndex: 4,
    previewPath: "/asset-store/" + "aa".repeat(32),
    previewBasis: "measured",
    slots: [
      { key: "headline", kind: "text", fallback: "The captured headline" },
      { key: "art", kind: "image", fallback: null },
      { key: "cta", kind: "href", fallback: "https://insight.example/demo" },
      { key: "visible", kind: "visibility", fallback: true }
    ],
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
    retirement: { allowed: false, reason: "not_a_repair", message: null },
    ...overrides
  };
}

function mount(params: { node?: WebNode; card?: FragmentCard | null } = {}) {
  const applyProps = vi.fn();
  const onGeneratePreview = vi.fn();
  const onActivate = vi.fn();
  const onRetire = vi.fn();
  render(
    <WebFragmentInspector
      node={params.node ?? NODE}
      card={params.card === undefined ? card() : params.card}
      cardStatus={params.card === null ? "loading" : "ready"}
      cardError={null}
      documentAssets={[
        { id: "asset_ward_1", label: "Ward photo" },
        { id: "asset_logo_1", label: "Logo" }
      ]}
      busy={false}
      applyProps={applyProps}
      onGeneratePreview={onGeneratePreview}
      onActivate={onActivate}
      onRetire={onRetire}
      actionBusy={false}
      actionError={null}
    />
  );
  return { applyProps, onGeneratePreview, onActivate, onRetire };
}

describe("the cloned-section card", () => {
  it("edits every slot kind through one whole-props write and nothing else", () => {
    const { applyProps } = mount();

    fireEvent.change(screen.getByLabelText("headline"), {
      target: { value: "Care, on your terms" }
    });
    fireEvent.blur(screen.getByLabelText("headline"));
    expect(applyProps).toHaveBeenLastCalledWith(
      {
        kind: "fragment",
        fragment_id: FRAGMENT_ID,
        slots: { headline: { text: "Care, on your terms" } }
      },
      "set_fragment_slot_text"
    );

    // The asset picker offers the DOCUMENT'S assets — an asset slot resolves through
    // `doc.assets` or the write is refused (LUMW0035), so anything else would be a refusal
    // wearing an option's clothes.
    const picker = screen.getByLabelText("art") as HTMLSelectElement;
    expect(
      Array.from(picker.options).map((option) => option.value)
    ).toEqual(["", "asset_ward_1", "asset_logo_1"]);
    fireEvent.change(picker, { target: { value: "asset_ward_1" } });
    expect(applyProps).toHaveBeenLastCalledWith(
      {
        kind: "fragment",
        fragment_id: FRAGMENT_ID,
        slots: { art: { asset: "asset_ward_1" } }
      },
      "set_fragment_slot_asset"
    );

    fireEvent.click(screen.getByLabelText("visible"));
    expect(applyProps).toHaveBeenLastCalledWith(
      {
        kind: "fragment",
        fragment_id: FRAGMENT_ID,
        slots: { visible: { visible: false } }
      },
      "set_fragment_slot_visibility"
    );

    const link = screen.getByLabelText("cta (link)") as HTMLInputElement;
    expect(link.type).toBe("url");
    expect(link.placeholder).toBe("https://insight.example/demo");
    fireEvent.change(link, { target: { value: "https://insight.example/book" } });
    fireEvent.blur(link);
    expect(applyProps).toHaveBeenLastCalledWith(
      {
        kind: "fragment",
        fragment_id: FRAGMENT_ID,
        slots: { cta: { text: "https://insight.example/book" } }
      },
      "set_fragment_slot_href"
    );
  });

  it("shows where the band sat rather than a position in a list", () => {
    // One document-order counter numbers the visible AND hidden collections (F3.0 M3), so a
    // page that hides something has gaps — 4 here is where it sat, not the 5th visible band.
    mount({ card: card({ sectionIndex: 4 }) });
    expect(screen.getByText("Position on page").nextSibling).toHaveTextContent("4");
  });

  it("says a clone is broken, what that means, and lists its family", () => {
    const { onRetire } = mount({
      card: card({
        degraded: true,
        degradedReason: "dead_height",
        degradedNote: "the captured band is mostly artificial scroll height.",
        family: [
          {
            fragmentId: FRAGMENT_ID,
            label: "Products",
            status: "approved",
            degraded: true,
            degradedReason: "dead_height",
            derivedReason: null,
            previewPath: null,
            createdAt: null,
            derivedFrom: null,
            isRoot: true,
            retirement: { allowed: false, reason: "not_a_repair", message: null }
          },
          {
            fragmentId: "frag_repaired00000001",
            label: "Repaired — Products",
            status: "approved",
            degraded: false,
            degradedReason: null,
            derivedReason: "repair rung 3; trigger dead_height; natural height",
            previewPath: "/asset-store/" + "bb".repeat(32),
            createdAt: "2026-08-28T00:00:00Z",
            derivedFrom: FRAGMENT_ID,
            isRoot: false,
            retirement: { allowed: true, reason: null, message: null }
          }
        ]
      })
    });
    expect(screen.getByText(/Broken clone — dead_height/)).toBeTruthy();
    expect(screen.getByText(/artificial scroll height/)).toBeTruthy();
    expect(screen.getByText(/repair rung 3/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Retire repair" }));
    expect(onRetire).toHaveBeenCalledWith("frag_repaired00000001");
    // R17-3: the harvested original is in the list but gets no button, and says why.
    expect(screen.getAllByRole("button", { name: "Retire repair" })).toHaveLength(1);
    expect(screen.getByText(/kept as evidence/)).toBeTruthy();
  });

  it("offers a grandchild repair its own retire button from the original's card (R18-1)", () => {
    // A repair-of-a-repair is nobody's direct child except its own parent's, and its parent is
    // on no page — so a card built from direct children left it with a button nowhere at all.
    const member = (id: string, parent: string | null, isRoot: boolean) => ({
      fragmentId: id,
      label: id,
      status: "approved",
      degraded: false,
      degradedReason: null,
      derivedReason: null,
      previewPath: "/asset-store/" + "cc".repeat(32),
      createdAt: null,
      derivedFrom: parent,
      isRoot,
      retirement: { allowed: !isRoot, reason: isRoot ? "not_a_repair" : null, message: null }
    });
    const { onRetire } = mount({
      card: card({
        degraded: true,
        degradedReason: "dead_height",
        degradedNote: "broken.",
        lineageRoot: FRAGMENT_ID,
        family: [
          member(FRAGMENT_ID, null, true),
          member("frag_child000000001", FRAGMENT_ID, false),
          member("frag_grandchild0001", "frag_child000000001", false)
        ]
      })
    });
    const buttons = screen.getAllByRole("button", { name: "Retire repair" });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[1] as HTMLElement);
    expect(onRetire).toHaveBeenCalledWith("frag_grandchild0001");
  });

  it("says which clone a repair repairs and why", () => {
    mount({
      card: card({
        label: "Repaired — Products",
        derivedFrom: "frag_original00000001",
        derivedReason: "repair rung 2; trigger dead_height; equivalent carousel",
        repairsWhat: {
          fragmentId: "frag_original00000001",
          label: "Products",
          status: "approved",
          degraded: true,
          degradedReason: "dead_height",
          derivedReason: null,
          previewPath: null,
          createdAt: null
        },
        retirement: { allowed: true, reason: null, message: null }
      })
    });
    expect(screen.getByText(/Repairs/)).toHaveTextContent("Products");
    expect(screen.getByText(/repair rung 2/)).toBeTruthy();
  });

  it("names both candidates when two released repairs contest one band", () => {
    mount({
      card: card({
        degraded: true,
        degradedReason: "dead_height",
        degradedNote: "the captured band is mostly artificial scroll height.",
        lineageAmbiguous: ["frag_a0000000000001", "frag_b0000000000002"]
      })
    });
    expect(screen.getByText(/neither replaces the other/)).toBeTruthy();
    expect(screen.getByText(/Retire the one you do not want/)).toBeTruthy();
  });

  it("offers a hidden-on-source section its evidence, its picture, then the decision", () => {
    const { onGeneratePreview, onActivate } = mount({
      card: card({
        status: "dormant",
        previewPath: null,
        sectionIndex: 7,
        hiddenOnSource: {
          hidden: true,
          evidence: ["class token 'w-condition-invisible'", "the probe skipped this child"]
        },
        activation: {
          allowed: false,
          reason: "no_preview",
          message: "Generate an isolation render and then decide."
        }
      })
    });
    expect(screen.getByText(/The source site hides this section/)).toHaveTextContent(
      "position 7"
    );
    expect(screen.getByText("class token 'w-condition-invisible'")).toBeTruthy();
    // The decision is unavailable until there is something to look at — D-F8's whole condition.
    expect(screen.getByRole("button", { name: "Activate section" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Render preview" }));
    expect(onGeneratePreview).toHaveBeenCalledWith(FRAGMENT_ID);
    expect(onActivate).not.toHaveBeenCalled();
  });

  it("enables the decision once the isolation render exists, and says what kind of picture it is", () => {
    const { onActivate } = mount({
      card: card({
        status: "dormant",
        previewPath: "/asset-store/" + "cc".repeat(32),
        previewBasis: "isolation_render",
        hiddenOnSource: { hidden: true, evidence: ["aria-hidden=\"true\""] },
        activation: { allowed: true, reason: null, message: null }
      })
    });
    // P-7: an isolation render and a source-site crop are not the same evidence, so the card
    // does not let a human mistake one for the other.
    expect(screen.getAllByText(/Isolation render/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Activate section" }));
    expect(onActivate).toHaveBeenCalledWith(FRAGMENT_ID);
  });

  it("offers no lineage card at all for a healthy, never-repaired clone", () => {
    mount({ card: card({ family: [] }) });
    expect(screen.queryByText("Condition & repairs")).toBeNull();
    expect(screen.queryByText("Hidden on source site")).toBeNull();
  });
});

describe("the hidden-on-source list", () => {
  it("is how a section that is on no page is reached at all", () => {
    const onActivate = vi.fn();
    const onGeneratePreview = vi.fn();
    render(
      <WebDormantSectionsCard
        sections={[
          card({
            fragmentId: "frag_hidden0000001",
            label: "Proof — Pricing",
            status: "dormant",
            previewPath: null,
            hiddenOnSource: { hidden: true, evidence: ["class token 'hide'"] },
            activation: {
              allowed: false,
              reason: "no_preview",
              message: "Generate an isolation render and then decide."
            }
          })
        ]}
        busy={false}
        error={null}
        onGeneratePreview={onGeneratePreview}
        onActivate={onActivate}
      />
    );
    const panel = screen.getByText("Hidden on source site").closest("section") as HTMLElement;
    expect(within(panel).getByText("Proof — Pricing")).toBeTruthy();
    expect(within(panel).getAllByText(/never offered to the agent/).length).toBeGreaterThan(0);
    fireEvent.click(within(panel).getByRole("button", { name: "Render preview" }));
    expect(onGeneratePreview).toHaveBeenCalledWith("frag_hidden0000001");
  });

  it("renders nothing when the site hides nothing", () => {
    const { container } = render(
      <WebDormantSectionsCard
        sections={[]}
        busy={false}
        error={null}
        onGeneratePreview={vi.fn()}
        onActivate={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
  });
});
