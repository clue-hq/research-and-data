import assert from "node:assert/strict";
import test from "node:test";

import {
  addressKey,
  addressObjectId,
  validateBridgeMessage,
  webBridgeAnnotationsMessage,
  webBridgeEditTextMessage,
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

/** Slice 3 (R-A6): the clone text-edit gesture. A double-click on an element
 * inside a cloned band opens a constrained in-frame editor; committing it posts
 * one override, addressed by the very same structural path an annotation uses. */
test("a clone-text-commit validates into an address plus a normalised override", () => {
  const message = validateBridgeMessage(
    bridgeEvent({
      channel: WEB_BRIDGE_CHANNEL,
      nonce: NONCE,
      type: "clone-text-commit",
      address: { nodeId: "frg_a", path: ":nth-child(1) > :nth-child(2)", tag: "h2" },
      override: {
        text: "Better economics",
        bold: true,
        italic: false,
        underline: "yes",
        size: 2,
      },
    }),
    NONCE,
    SOURCE
  );

  assert.equal(message?.type, "clone-text-commit");
  assert.deepEqual(
    message?.type === "clone-text-commit" ? message.address : null,
    { nodeId: "frg_a", path: ":nth-child(1) > :nth-child(2)", slot: undefined, tag: "h2" }
  );
  assert.deepEqual(
    message?.type === "clone-text-commit" ? message.override : null,
    // Only a literal `true` is a mark: the frame is untrusted, so a truthy
    // string must not silently become an underline.
    { text: "Better economics", bold: true, italic: false, underline: false, size: 2 }
  );
});

test("the override's size step is clamped to the engine's ramp, and 0 is omitted", () => {
  const commit = (size: unknown) =>
    validateBridgeMessage(
      bridgeEvent({
        channel: WEB_BRIDGE_CHANNEL,
        nonce: NONCE,
        type: "clone-text-commit",
        address: { nodeId: "frg_a", path: ":nth-child(1)", tag: "h2" },
        override: { text: "x", bold: false, italic: false, underline: false, size },
      }),
      NONCE,
      SOURCE
    );

  const big = commit(99);
  assert.equal(big?.type === "clone-text-commit" ? big.override.size : null, 3);
  const small = commit(-99);
  assert.equal(small?.type === "clone-text-commit" ? small.override.size : null, -3);
  // `size` is OPTIONAL on the engine's override and 0 means "no step" — so a
  // zero, an absent one and a non-numeric one all leave the key off entirely.
  for (const absent of [0, undefined, "2", Number.NaN]) {
    const none = commit(absent);
    assert.equal(none?.type, "clone-text-commit");
    assert.equal(
      none?.type === "clone-text-commit" ? "size" in none.override : true,
      false,
      `size ${String(absent)} must be omitted`
    );
  }
});

test("the override's text is capped at 8192 BYTES, never split mid-character", () => {
  // A 3-byte character straddling the cap: 8191 ASCII bytes then one "€". The
  // cap is measured in UTF-8 bytes (what the server stores), so the euro sign
  // cannot fit and must be dropped WHOLE rather than truncated into a lone
  // surrogate/continuation byte.
  const text = "a".repeat(8191) + "\u20ac" + "tail";
  const message = validateBridgeMessage(
    bridgeEvent({
      channel: WEB_BRIDGE_CHANNEL,
      nonce: NONCE,
      type: "clone-text-commit",
      address: { nodeId: "frg_a", path: ":nth-child(1)", tag: "h2" },
      override: { text, bold: false, italic: false, underline: false },
    }),
    NONCE,
    SOURCE
  );

  const capped =
    message?.type === "clone-text-commit" ? message.override.text : "";
  assert.equal(capped, "a".repeat(8191));
  assert.ok(new TextEncoder().encode(capped).length <= 8192);
});

test("a clone-text-commit without a path, or with a malformed override, is dropped", () => {
  // A clone edit has no meaning on a vocabulary node — that text is the
  // engine's own, edited through the rich-text session, not an override.
  assert.equal(
    validateBridgeMessage(
      bridgeEvent({
        channel: WEB_BRIDGE_CHANNEL,
        nonce: NONCE,
        type: "clone-text-commit",
        address: { nodeId: "txt", tag: "p" },
        override: { text: "x", bold: false, italic: false, underline: false },
      }),
      NONCE,
      SOURCE
    ),
    null
  );

  for (const override of [undefined, null, "text", { text: 7 }, {}]) {
    assert.equal(
      validateBridgeMessage(
        bridgeEvent({
          channel: WEB_BRIDGE_CHANNEL,
          nonce: NONCE,
          type: "clone-text-commit",
          address: { nodeId: "frg_a", path: ":nth-child(1)", tag: "h2" },
          override,
        }),
        NONCE,
        SOURCE
      ),
      null,
      `override ${JSON.stringify(override)} must be dropped`
    );
  }
});

test("a clone-text-cancel validates into the bare address", () => {
  const message = validateBridgeMessage(
    bridgeEvent({
      channel: WEB_BRIDGE_CHANNEL,
      nonce: NONCE,
      type: "clone-text-cancel",
      address: { nodeId: "frg_a", path: ":nth-child(1)", slot: "headline", tag: "h2" },
    }),
    NONCE,
    SOURCE
  );

  assert.deepEqual(message, {
    type: "clone-text-cancel",
    address: { nodeId: "frg_a", path: ":nth-child(1)", slot: "headline", tag: "h2" },
  });
});

test("the edit-text message posted INTO the frame carries the render nonce", () => {
  assert.deepEqual(
    webBridgeEditTextMessage(NONCE, {
      nodeId: "frg_a",
      path: ":nth-child(1)",
      tag: "h2",
    }),
    {
      channel: WEB_BRIDGE_CHANNEL,
      nonce: NONCE,
      type: "edit-text",
      address: { nodeId: "frg_a", path: ":nth-child(1)", tag: "h2" },
    }
  );
});
