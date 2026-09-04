import assert from "node:assert/strict";
import test from "node:test";

import {
  addressKey,
  addressObjectId,
  validateBridgeMessage,
  webBridgeAnnotationsMessage,
  WEB_BRIDGE_CHANNEL,
} from "./webBridge";

const SOURCE = { name: "the-iframe-window" };
const NONCE = "render-nonce-1";

/** A srcdoc bridge message as the parent sees it: null origin, the frame's own
 * window as `source`, channel-tagged and nonce-tagged. */
function bridgeEvent(data: Record<string, unknown>, source: unknown = SOURCE) {
  return { data, origin: "null", source } as unknown as MessageEvent;
}

/** F5 task 20: a click on a site-internal link inside the editor canvas is
 * swallowed by the injected bridge and re-posted as a navigation intent. The
 * parser admits it under exactly the selection messages' authenticity rules. */
test("a nonce-carrying lumen:navigate message parses to a navigate intent", () => {
  const message = validateBridgeMessage(
    bridgeEvent({
      channel: WEB_BRIDGE_CHANNEL,
      nonce: NONCE,
      type: "lumen:navigate",
      pageId: "pricing",
    }),
    NONCE,
    SOURCE
  );

  assert.deepEqual(message, { type: "navigate", pageId: "pricing" });
});

test("a lumen:navigate message from a stale render is dropped", () => {
  const message = validateBridgeMessage(
    bridgeEvent({
      channel: WEB_BRIDGE_CHANNEL,
      nonce: "a-previous-render",
      type: "lumen:navigate",
      pageId: "pricing",
    }),
    NONCE,
    SOURCE
  );

  assert.equal(message, null);
});

test("a lumen:navigate message without a page id is dropped", () => {
  for (const pageId of [undefined, "", 7]) {
    const message = validateBridgeMessage(
      bridgeEvent({
        channel: WEB_BRIDGE_CHANNEL,
        nonce: NONCE,
        type: "lumen:navigate",
        pageId,
      }),
      NONCE,
      SOURCE
    );

    assert.equal(message, null, `pageId ${String(pageId)} must not navigate`);
  }
});

/** Slice 2 (R-A1): the bridge's element-level `annotate` report. The address
 * grammar is shared with the turn's `design_node` object ids (spec §3.5), so
 * the two serialisers live beside the validator and are pinned with it. */
test("an annotate message is validated into a typed event, and addresses key/serialise per spec §3.5", () => {
  const message = validateBridgeMessage(
    bridgeEvent({
      channel: WEB_BRIDGE_CHANNEL,
      nonce: NONCE,
      type: "annotate",
      address: {
        nodeId: "frg_a",
        path: ":nth-child(2)",
        slot: "headline",
        tag: "h2",
      },
      name: "h2 · headline",
      textLike: true,
      geometry: {
        viewport: { x: 0, y: 0, width: 1, height: 1 },
        document: { x: 0, y: 0, width: 1, height: 1 },
      },
    }),
    NONCE,
    SOURCE
  );

  assert.equal(message?.type, "annotate");
  assert.deepEqual(
    message?.type === "annotate" ? message.event.address : null,
    { nodeId: "frg_a", path: ":nth-child(2)", slot: "headline", tag: "h2" }
  );
  assert.equal(
    addressObjectId({ nodeId: "frg_a", path: ":nth-child(2)", tag: "h2" }),
    "frg_a#:nth-child(2)"
  );
  assert.equal(addressObjectId({ nodeId: "txt", tag: "p" }), "txt");
  assert.equal(addressKey({ nodeId: "txt", tag: "p" }), "txt#");
});

test("an annotate message with a malformed path drops the path, and one without an address is dropped", () => {
  const withBadPath = validateBridgeMessage(
    bridgeEvent({
      channel: WEB_BRIDGE_CHANNEL,
      nonce: NONCE,
      type: "annotate",
      address: { nodeId: "frg_a", path: "div > .headline", tag: "h2" },
      geometry: {
        viewport: { x: 0, y: 0, width: 1, height: 1 },
        document: { x: 0, y: 0, width: 1, height: 1 },
      },
    }),
    NONCE,
    SOURCE
  );
  assert.equal(withBadPath?.type, "annotate");
  assert.equal(
    withBadPath?.type === "annotate" ? withBadPath.event.address.path : "unset",
    undefined
  );
  // No name posted → the tag stands in, and the element is not text-like.
  assert.equal(
    withBadPath?.type === "annotate" ? withBadPath.event.name : null,
    "h2"
  );
  assert.equal(
    withBadPath?.type === "annotate" ? withBadPath.event.textLike : null,
    false
  );

  assert.equal(
    validateBridgeMessage(
      bridgeEvent({
        channel: WEB_BRIDGE_CHANNEL,
        nonce: NONCE,
        type: "annotate",
        geometry: {
          viewport: { x: 0, y: 0, width: 1, height: 1 },
          document: { x: 0, y: 0, width: 1, height: 1 },
        },
      }),
      NONCE,
      SOURCE
    ),
    null
  );
});

test("the annotations message posted INTO the frame carries the render nonce", () => {
  assert.deepEqual(
    webBridgeAnnotationsMessage(NONCE, [
      { address: { nodeId: "frg_a", path: ":nth-child(2)", tag: "h2" }, n: 1 },
    ]),
    {
      channel: WEB_BRIDGE_CHANNEL,
      nonce: NONCE,
      type: "annotations",
      items: [
        { address: { nodeId: "frg_a", path: ":nth-child(2)", tag: "h2" }, n: 1 },
      ],
    }
  );
  assert.deepEqual(webBridgeAnnotationsMessage(NONCE, []).items, []);
});
