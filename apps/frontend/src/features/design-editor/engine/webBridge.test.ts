import assert from "node:assert/strict";
import test from "node:test";

import { WEB_BRIDGE_CHANNEL, validateBridgeMessage } from "./webBridge";

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
