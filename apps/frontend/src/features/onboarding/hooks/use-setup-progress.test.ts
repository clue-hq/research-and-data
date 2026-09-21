import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { SetupApiError } from "../data/setup";
import { useSetupProgress, type SetupProgress } from "./use-setup-progress";

test("missing website recovery uses the normal setup source and prevents duplicate submissions", async () => {
  const dom = new JSDOM("<div id='root'></div>");
  const saved = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document,
    navigator: dom.window.navigator, IS_REACT_ACT_ENVIRONMENT: true })) {
    saved.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, value });
  }
  let latest: SetupProgress;
  const starts: string[] = [];
  let release: (() => void) | undefined;
  const source = {
    start: async ({ companyWebsite }: { companyWebsite: string }) => {
      starts.push(companyWebsite);
      if (!companyWebsite) throw new SetupApiError("Missing website", { status: 422, code: "company_domain_missing" });
      await new Promise<void>((resolve) => { release = resolve; });
      throw new Error("Transport failed");
    },
    read: async () => ({ status: "none" as const, run_id: null, steps: [], brand_kit_ingestion: null }),
  };
  function Probe() { latest = useSetupProgress({ companyWebsite: "" }, source); return null; }
  const root = createRoot(dom.window.document.getElementById("root")!);
  try {
    await act(async () => { root.render(createElement(Probe)); });
    assert.equal(latest!.needsWebsite, true);
    await act(async () => { latest!.setRecoveryWebsite("https://example.com"); });
    await act(async () => { void latest!.submitWebsite(); void latest!.submitWebsite(); });
    assert.deepEqual(starts, ["", "https://example.com"]);
    assert.equal(latest!.recoveryBusy, true);
    await act(async () => { release!(); });
    assert.equal(latest!.needsWebsite, true);
    assert.equal(latest!.recoveryBusy, false);
    assert.match(latest!.recoveryError ?? "", /try again/i);
  } finally {
    await act(async () => { root.unmount(); });
    dom.window.close();
    for (const [key, descriptor] of saved) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
});
