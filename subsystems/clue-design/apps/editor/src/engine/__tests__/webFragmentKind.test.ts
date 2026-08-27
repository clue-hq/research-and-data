/**
 * The editor tolerates a `fragment` node (clone-fidelity F1.3).
 *
 * F1.1 added `WebNodeKind::Fragment` to the engine's node union, and F1.3 makes it render. The
 * inspector UI for a fragment is Phase F3's — but a document that carries one is handed to this
 * editor by every read path it has the moment it exists, so "nothing here crashes or rejects it"
 * has to be true between the phases, not after them.
 *
 * This pins the degrade, not a feature: the node's identity survives the type, and the canvas
 * gesture planners refuse it the way they already refuse an embed. When F3 gives fragments real
 * affordances these expectations change on purpose, and the change is visible here.
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

  it("is offered neither drag-move nor resize on the canvas", () => {
    expect(planCanvasNodeMove(PAGE, "frg_hero", "root", 0)).toBeNull();
    expect(planCanvasNodeResize(PAGE, "frg_hero", 640, null)).toBeNull();
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
