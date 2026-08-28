/**
 * What a `fragment` node may be gestured into (clone-fidelity F1.3, amended by F3.2).
 *
 * F1.1 added `WebNodeKind::Fragment` to the engine's node union and F1.3 made it render; between
 * those phases this file pinned the DEGRADE — a fragment was offered no gesture at all, the way
 * an embed is not.
 *
 * F3.2 replaces half of that with founder ruling **D-F3 (Option A, top-level reordering only)**:
 * a whole cloned band CAN be moved up or down the page, and can never be manually resized, be a
 * drop target for ordinary nodes, be internally re-laid-out, or be detached into editable nested
 * elements. So the move expectation flips on purpose and the resize expectation does not — which
 * is exactly the change this file's older wording said would become visible here.
 */
import { describe, expect, it } from "vitest";

import {
  planCanvasNodeMove,
  planCanvasNodeResize,
  type WebNode,
  type WebPageSummary
} from "../webDocuments";

const FRAGMENT: WebNode = {
  id: "frg_hero",
  kind: "fragment",
  classes: "w-full py-12",
  fragment_id: "frag_0123456789abcdef",
  slots: { headline: { text: "Talk to us" } }
};

const PAGE = {
  id: "home",
  root: "root",
  nodes: {
    root: { id: "root", kind: "container", classes: "", children: ["sec_a"] },
    sec_a: { id: "sec_a", kind: "section", classes: "", children: ["frg_hero"] },
    frg_hero: FRAGMENT
  }
} as unknown as WebPageSummary;

describe("a fragment node in the editor", () => {
  it("keeps its artifact pin and slot values through the node type", () => {
    expect(FRAGMENT.fragment_id).toBe("frag_0123456789abcdef");
    expect(FRAGMENT.slots?.headline).toEqual({ text: "Talk to us" });
  });

  it("reorders inside its parent but is never resized (D-F3)", () => {
    const page = {
      id: "home",
      root: "root",
      nodes: {
        root: { id: "root", kind: "container", classes: "", children: ["sec_a"] },
        sec_a: {
          id: "sec_a",
          kind: "section",
          classes: "",
          children: ["txt_a", "frg_hero"]
        },
        txt_a: { id: "txt_a", kind: "text", classes: "" },
        frg_hero: FRAGMENT
      }
    } as unknown as WebPageSummary;
    // Moved UP the page, past its sibling — the positive half of the ruling.
    const up = planCanvasNodeMove(page, "frg_hero", "sec_a", 0);
    expect(up?.intent).toBe("reorder_node");
    // …and back down again.
    expect(planCanvasNodeMove(page, "frg_hero", "sec_a", 0)?.operation).toBeTruthy();
    // Never resized: a cloned band's proportions are the clone.
    expect(planCanvasNodeResize(page, "frg_hero", 640, null)).toBeNull();
  });

  it("is never a drop target, and never a direct child of the page root", () => {
    const page = {
      id: "home",
      root: "root",
      nodes: {
        root: { id: "root", kind: "container", classes: "", children: ["sec_a"] },
        sec_a: {
          id: "sec_a",
          kind: "section",
          classes: "",
          children: ["frg_hero", "txt_a"]
        },
        frg_hero: FRAGMENT,
        txt_a: { id: "txt_a", kind: "text", classes: "" }
      }
    } as unknown as WebPageSummary;
    // Dropping an ordinary node INSIDE the clone would be an internal edit of somebody else's
    // section — refused, and the fragment stays a leaf.
    expect(planCanvasNodeMove(page, "txt_a", "frg_hero", 0)).toBeNull();
    // The page root holds sections and nothing else (LUMW0011), so the wrapper moves, not the
    // fragment: "top-level reordering" is the wrapper's job, and the pair travels together.
    expect(planCanvasNodeMove(page, "frg_hero", "root", 0)).toBeNull();
  });

  it("does not stop its siblings from being planned", () => {
    const page = {
      id: "home",
      root: "root",
      nodes: {
        root: { id: "root", kind: "container", classes: "", children: ["sec_a"] },
        sec_a: {
          id: "sec_a",
          kind: "section",
          classes: "",
          children: ["frg_hero", "txt_a"]
        },
        frg_hero: FRAGMENT,
        txt_a: { id: "txt_a", kind: "text", classes: "" }
      }
    } as unknown as WebPageSummary;
    expect(planCanvasNodeResize(page, "txt_a", 320, null)).not.toBeNull();
  });
});
