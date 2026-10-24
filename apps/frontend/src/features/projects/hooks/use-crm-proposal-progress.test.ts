import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { useCrmProposalProgress } from "./use-crm-proposal-progress";

/**
 * R-12.18 (live check L-16): a sending CRM card keeps reading its proposal while the tab is hidden
 * (every 15 s; 2 s when shown), and reads at once when the chat receives the "changes finished"
 * wake-up. Only `fetch`, the page's visibility and the window's timers are faked.
 */

const PROPOSAL = "proposal-1";

function progress(state: "sending" | "done") {
  const tally = { done: 0, failed: 0, skipped: 0, pending: state === "sending" ? 1 : 0 };
  return {
    proposalId: PROPOSAL, state, provider: "hubspot", counts: tally, groups: [], overwrites: [],
    failed: [], skipped: [], answeredBy: null, answeredByName: null, answeredAt: null,
  };
}

function harness({ hidden }: { hidden: boolean }) {
  const dom = new JSDOM("<div id='root'></div>");
  const visibility = hidden ? "hidden" : "visible";
  Object.defineProperty(dom.window.document, "visibilityState", {
    configurable: true,
    get: () => visibility,
  });
  /** Every timer the hook set, by delay; none fires unless a test runs it. */
  const timers: Array<{ ms: number; run: () => void; cleared: boolean }> = [];
  Object.assign(dom.window, {
    setTimeout: (run: () => void, ms: number) => timers.push({ ms, run, cleared: false }),
    clearTimeout: (id: number | undefined) => {
      if (id !== undefined && timers[id - 1]) timers[id - 1]!.cleared = true;
    },
  });
  const originals = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({
    window: dom.window,
    document: dom.window.document,
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
  let latest: ReturnType<typeof useCrmProposalProgress> = null;
  function Probe({ wake }: { wake: number }) {
    latest = useCrmProposalProgress(PROPOSAL, true, wake);
    return null;
  }
  const root = createRoot(dom.window.document.getElementById("root")!);
  async function settle() {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      await act(async () => { await new Promise<void>((resolve) => setImmediate(resolve)); });
    }
  }
  return {
    server,
    timers,
    state: () => latest?.state ?? null,
    async render(wake = 0) {
      await act(async () => { root.render(createElement(Probe, { wake })); });
      await settle();
    },
    pending: () => timers.filter((timer) => !timer.cleared),
    async teardown() {
      await act(async () => { root.unmount(); });
      globalThis.fetch = oldFetch;
      dom.window.close();
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else Reflect.deleteProperty(globalThis, key);
      }
    },
  };
}

test("a hidden tab keeps reading a sending card, every 15 s", async () => {
  const h = harness({ hidden: true });
  try {
    await h.render();
    assert.equal(h.server.reads, 1, "the card read its proposal while hidden");
    assert.deepEqual(h.pending().map((timer) => timer.ms), [15_000]);
  } finally {
    await h.teardown();
  }
});

test("a shown tab re-reads a sending card every 2 s", async () => {
  const h = harness({ hidden: false });
  try {
    await h.render();
    assert.equal(h.server.reads, 1);
    assert.deepEqual(h.pending().map((timer) => timer.ms), [2_000]);
  } finally {
    await h.teardown();
  }
});

test("the changes-finished wake-up re-reads the card at once", async () => {
  const h = harness({ hidden: true });
  try {
    await h.render(0);
    assert.equal(h.server.reads, 1);
    h.server.answer = progress("done");
    await h.render(1);
    assert.equal(h.server.reads, 2, "read at once, without waiting for the 15 s timer");
    assert.equal(h.state(), "done");
    assert.deepEqual(h.pending(), [], "a finished card stops reading");
  } finally {
    await h.teardown();
  }
});
