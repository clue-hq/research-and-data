import assert from "node:assert/strict";
import Module from "node:module";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import type { ChatGatePart } from "../model/chat-parts";
import type { GateCardModel } from "../model/chat-gate";

/**
 * R-12.18 end to end below the controller: the chat's count of "changes finished" wake-up turns
 * (`crmWritesFinished`) reaches a sending CRM write card through the part actions, and the card
 * reads its proposal at once. Only `fetch`, the page's visibility and the window's timers are
 * faked; the part view, the card and the hook run for real. CSS modules load as class-name
 * stubs (node cannot parse CSS).
 */

(Module as unknown as { _extensions: Record<string, (m: { exports: unknown }) => void> })
  ._extensions[".css"] = (m) => {
  m.exports = { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
};

const PROPOSAL = "proposal-wake";

function progress(state: "sending" | "done") {
  const tally = { done: state === "done" ? 1 : 0, failed: 0, skipped: 0, pending: state === "sending" ? 1 : 0 };
  return {
    proposalId: PROPOSAL, state, provider: "hubspot", counts: tally, groups: [], overwrites: [],
    failed: [], skipped: [], answeredBy: "usr_1", answeredByName: "Ana", answeredAt: null,
  };
}

const card = {
  gateId: "gate-wake",
  state: "responded",
  kind: "crm_write_permission",
  crmProposalId: PROPOSAL,
  crmWrite: {
    provider: "hubspot", providerName: "HubSpot", title: "Clue wants to update HubSpot",
    description: "", caption: "", groups: [], overwritesHeading: null, overwrites: [],
    standingPermissions: [],
  },
} as unknown as GateCardModel;

const part = { kind: "gate", partId: "part-wake" } as unknown as ChatGatePart;

test("a crm_writes_finished wake-up makes a sending card read its proposal at once", async () => {
  const dom = new JSDOM("<div id='root'></div>", { url: "https://clue.invalid/" });
  Object.defineProperty(dom.window.document, "visibilityState", {
    configurable: true,
    get: () => "hidden",
  });
  const timers: number[] = [];
  Object.assign(dom.window, {
    setTimeout: (_run: () => void, ms: number) => timers.push(ms),
    clearTimeout: () => undefined,
  });
  const originals = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  const oldFetch = globalThis.fetch;
  const server = { reads: 0, answer: progress("sending") };
  globalThis.fetch = async (input) => {
    assert.match(String(input), new RegExp(`/crm/proposals/${PROPOSAL}$`));
    server.reads += 1;
    return Response.json(server.answer);
  };
  const { ChatMessagePartView } = await import("./chat-message-part");
  const root = createRoot(dom.window.document.getElementById("root")!);
  const render = async (crmWritesFinished: number) => {
    await act(async () => {
      root.render(createElement(ChatMessagePartView, {
        part,
        actions: {
          busy: false,
          gateFor: () => card,
          onGateDecision: () => undefined,
          onGateRecovery: () => undefined,
          crmWritesFinished,
        },
      }));
    });
    for (let attempt = 0; attempt < 10; attempt += 1) {
      await act(async () => { await new Promise<void>((resolve) => setImmediate(resolve)); });
    }
  };
  try {
    await render(0);
    assert.equal(server.reads, 1, "the answered card read its proposal");
    assert.deepEqual(timers, [15_000], "and waits 15 s while the tab is hidden");
    server.answer = progress("done");
    await render(1);
    assert.equal(server.reads, 2, "the wake-up read it at once");
  } finally {
    await act(async () => { root.unmount(); });
    globalThis.fetch = oldFetch;
    dom.window.close();
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
});
