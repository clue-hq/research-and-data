import { describe, expect, it } from "vitest";

import {
  selectionChipLabel,
  selectionKindLabel,
  validateBridgeMessage,
  webBridgeClearMessage,
  webBridgeComponentPreviewMessage,
  webBridgeInspectNodeMessage,
  webBridgeSelectNodeMessage,
  type WebSelection
} from "../webBridge";

/** Build a jsdom MessageEvent with an arbitrary source/origin. The real bridge
 * posts from a srcdoc sandbox frame (origin === "null", source === that frame's
 * contentWindow); source/origin are read-only getters, so we override them on
 * the instance. */
function makeEvent(opts: { data: unknown; origin: string; source: unknown }): MessageEvent {
  const event = new MessageEvent("message", { data: opts.data });
  Object.defineProperty(event, "origin", { value: opts.origin, configurable: true });
  Object.defineProperty(event, "source", { value: opts.source, configurable: true });
  return event;
}

const FRAME = { marker: "iframe-window" };
const NONCE = "3f2a-nonce";

function selectData(node: unknown, overrides: Record<string, unknown> = {}) {
  return { channel: "lumen-web-bridge", nonce: NONCE, type: "select", node, ...overrides };
}

const HERO_NODE = { nodeId: "hero", tag: "section", tv: false, btn: false, text: "Welcome" };

describe("validateBridgeMessage", () => {
  it("accepts a valid select from the expected frame with the current nonce", () => {
    const event = makeEvent({ data: selectData(HERO_NODE), origin: "null", source: FRAME });
    const result = validateBridgeMessage(event, NONCE, FRAME);
    expect(result).toEqual(
      expect.objectContaining({
      type: "select",
        selection: expect.objectContaining({
          nodeId: "hero",
          tag: "section",
          tv: false,
          btn: false,
          text: "Welcome",
          parentNodeId: null,
          childNodeIds: []
        })
      })
    );
  });

  it("rejects a message from a different source window", () => {
    const event = makeEvent({ data: selectData(HERO_NODE), origin: "null", source: {} });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toBeNull();
  });

  it("rejects a non-null origin (not a srcdoc sandbox frame)", () => {
    const event = makeEvent({
      data: selectData(HERO_NODE),
      origin: "https://evil.example",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toBeNull();
  });

  it("rejects a stale nonce from a previous render", () => {
    const event = makeEvent({
      data: selectData(HERO_NODE, { nonce: "old-nonce" }),
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toBeNull();
  });

  it("rejects a foreign channel", () => {
    const event = makeEvent({
      data: selectData(HERO_NODE, { channel: "some-other-bus" }),
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toBeNull();
  });

  it("rejects a nullish expected source (frame not mounted yet)", () => {
    const event = makeEvent({ data: selectData(HERO_NODE), origin: "null", source: null });
    expect(validateBridgeMessage(event, NONCE, null)).toBeNull();
  });

  it("rejects an empty expected nonce", () => {
    const event = makeEvent({
      data: selectData(HERO_NODE, { nonce: "" }),
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, "", FRAME)).toBeNull();
  });

  it("treats a select with no node as a cleared selection", () => {
    const event = makeEvent({ data: selectData(null), origin: "null", source: FRAME });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toEqual({
      type: "select",
      selection: null
    });
  });

  it("passes a ready message through", () => {
    const event = makeEvent({
      data: { channel: "lumen-web-bridge", nonce: NONCE, type: "ready" },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toEqual({ type: "ready" });
  });

  it("coerces geometry and computed styles from a node-info update", () => {
    const event = makeEvent({
      data: {
        channel: "lumen-web-bridge",
        nonce: NONCE,
        type: "node-info",
        node: {
          ...HERO_NODE,
          parentNodeId: "root",
          childNodeIds: ["headline"],
          geometry: {
            viewport: { x: 5.5, y: 7, width: 900, height: 320 },
            document: { x: 5.5, y: 107, width: 900, height: 320 }
          },
          computedStyle: {
            authoredClasses: "flex gap-4",
            display: "flex",
            paddingTop: "16px",
            fontSize: "16px"
          }
        }
      },
      origin: "null",
      source: FRAME
    });
    const result = validateBridgeMessage(event, NONCE, FRAME);
    expect(result).toEqual(
      expect.objectContaining({
        type: "node-info",
        node: expect.objectContaining({
          nodeId: "hero",
          parentNodeId: "root",
          childNodeIds: ["headline"],
          geometry: expect.objectContaining({
            viewport: expect.objectContaining({ x: 5.5, width: 900, height: 320 }),
            document: expect.objectContaining({ y: 107 })
          }),
          computedStyle: expect.objectContaining({
            authoredClasses: "flex gap-4",
            display: "flex",
            paddingTop: "16px",
            fontSize: "16px"
          })
        })
      })
    );
  });

  it("rejects node-info without a stable node id", () => {
    const event = makeEvent({
      data: {
        channel: "lumen-web-bridge",
        nonce: NONCE,
        type: "node-info",
        node: { tag: "div" }
      },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toBeNull();
  });

  it("ignores unknown message types", () => {
    const event = makeEvent({
      data: { channel: "lumen-web-bridge", nonce: NONCE, type: "hover" },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toBeNull();
  });

  it("passes an edit-start through with its node id", () => {
    const event = makeEvent({
      data: { channel: "lumen-web-bridge", nonce: NONCE, type: "edit-start", nodeId: "headline" },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toEqual({
      type: "edit-start",
      nodeId: "headline"
    });
  });

  it("rejects an edit-start without a node id", () => {
    const event = makeEvent({
      data: { channel: "lumen-web-bridge", nonce: NONCE, type: "edit-start" },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toBeNull();
  });

  it("passes a text-commit through with node id + html", () => {
    const event = makeEvent({
      data: {
        channel: "lumen-web-bridge",
        nonce: NONCE,
        type: "text-commit",
        nodeId: "headline",
        html: "Hello <strong>world</strong>"
      },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toEqual({
      type: "text-commit",
      nodeId: "headline",
      html: "Hello <strong>world</strong>"
    });
  });

  it("passes a generic move-node destination through", () => {
    const event = makeEvent({
      data: {
        channel: "lumen-web-bridge",
        nonce: NONCE,
        type: "move-node",
        nodeId: "cta",
        newParentNodeId: "secondary_stack",
        index: 2
      },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toEqual({
      type: "move-node",
      nodeId: "cta",
      newParentNodeId: "secondary_stack",
      index: 2
    });
  });

  it("rejects malformed or negative move-node destinations", () => {
    const noId = makeEvent({
      data: {
        channel: "lumen-web-bridge",
        nonce: NONCE,
        type: "move-node",
        newParentNodeId: "stack",
        index: 1
      },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(noId, NONCE, FRAME)).toBeNull();
    const badIndex = makeEvent({
      data: {
        channel: "lumen-web-bridge",
        nonce: NONCE,
        type: "move-node",
        nodeId: "cta",
        newParentNodeId: "stack",
        index: -1
      },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(badIndex, NONCE, FRAME)).toBeNull();
  });

  it("passes width-only, height-only, and corner resize intents", () => {
    const corner = makeEvent({
      data: {
        channel: "lumen-web-bridge",
        nonce: NONCE,
        type: "resize-node",
        nodeId: "cta",
        widthPx: 240,
        heightPx: 56
      },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(corner, NONCE, FRAME)).toEqual({
      type: "resize-node",
      nodeId: "cta",
      widthPx: 240,
      heightPx: 56
    });

    const widthOnly = makeEvent({
      data: {
        channel: "lumen-web-bridge",
        nonce: NONCE,
        type: "resize-node",
        nodeId: "copy",
        widthPx: 360
      },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(widthOnly, NONCE, FRAME)).toEqual({
      type: "resize-node",
      nodeId: "copy",
      widthPx: 360,
      heightPx: null
    });
  });

  it("rejects malformed resize intents", () => {
    for (const payload of [
      { nodeId: "", widthPx: 120, heightPx: null },
      { nodeId: "copy", widthPx: null, heightPx: null },
      { nodeId: "copy", widthPx: -1, heightPx: null },
      { nodeId: "copy", widthPx: "120", heightPx: null }
    ]) {
      const event = makeEvent({
        data: {
          channel: "lumen-web-bridge",
          nonce: NONCE,
          type: "resize-node",
          ...payload
        },
        origin: "null",
        source: FRAME
      });
      expect(validateBridgeMessage(event, NONCE, FRAME)).toBeNull();
    }
  });

  it("defaults a text-commit's missing html to an empty string", () => {
    const event = makeEvent({
      data: { channel: "lumen-web-bridge", nonce: NONCE, type: "text-commit", nodeId: "sub" },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toEqual({
      type: "text-commit",
      nodeId: "sub",
      html: ""
    });
  });

  it("rejects a stale-nonce text-commit", () => {
    const event = makeEvent({
      data: {
        channel: "lumen-web-bridge",
        nonce: "old-nonce",
        type: "text-commit",
        nodeId: "sub",
        html: "x"
      },
      origin: "null",
      source: FRAME
    });
    expect(validateBridgeMessage(event, NONCE, FRAME)).toBeNull();
  });
});

describe("selection labels", () => {
  const base: WebSelection = {
    nodeId: "cta",
    tag: "a",
    tv: false,
    btn: false,
    text: "",
    parentNodeId: null,
    childNodeIds: [],
    geometry: {
      viewport: { x: 0, y: 0, top: 0, right: 0, bottom: 0, left: 0, width: 0, height: 0 },
      document: { x: 0, y: 0, top: 0, right: 0, bottom: 0, left: 0, width: 0, height: 0 }
    },
    computedStyle: {} as WebSelection["computedStyle"]
  };

  it("labels a button, a text node, then falls back to the tag", () => {
    expect(selectionKindLabel({ ...base, btn: true })).toBe("button");
    expect(selectionKindLabel({ ...base, tv: true })).toBe("text");
    expect(selectionKindLabel({ ...base, tag: "section" })).toBe("section");
    expect(selectionKindLabel({ ...base, tag: "" })).toBe("element");
  });

  it("composes the chip label as `${nodeId} · ${kind}`", () => {
    expect(selectionChipLabel({ ...base, nodeId: "hero", tag: "section" })).toBe("hero · section");
  });
});

describe("webBridgeClearMessage", () => {
  it("carries the channel, nonce, and clear type", () => {
    expect(webBridgeClearMessage(NONCE)).toEqual({
      channel: "lumen-web-bridge",
      nonce: NONCE,
      type: "clear"
    });
  });
});

describe("webBridgeComponentPreviewMessage", () => {
  it("carries the channel, nonce, node id, and open/close action", () => {
    expect(webBridgeComponentPreviewMessage(NONCE, "dlg-1", "open")).toEqual({
      channel: "lumen-web-bridge",
      nonce: NONCE,
      type: "component-preview",
      nodeId: "dlg-1",
      action: "open"
    });
    expect(webBridgeComponentPreviewMessage(NONCE, "dlg-1", "close").action).toBe("close");
  });
});

describe("webBridgeSelectNodeMessage", () => {
  it("carries the channel, nonce, node id, and select-node type", () => {
    expect(webBridgeSelectNodeMessage(NONCE, "dlg-1")).toEqual({
      channel: "lumen-web-bridge",
      nonce: NONCE,
      type: "select-node",
      nodeId: "dlg-1"
    });
  });
});

describe("webBridgeInspectNodeMessage", () => {
  it("requests metrics without selecting the node", () => {
    expect(webBridgeInspectNodeMessage(NONCE, "hero-copy")).toEqual({
      channel: "lumen-web-bridge",
      nonce: NONCE,
      type: "inspect-node",
      nodeId: "hero-copy"
    });
  });
});
