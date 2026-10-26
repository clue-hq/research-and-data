import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { createWorkspaceFixture } from "../data/workspace.fixture";
import { approveEmail, saveEmail } from "../model/workspace";
import { useEmailDialogs } from "./use-email-dialogs";

test("open edit and approval retain the reviewed revision after another tab changes the message", async () => {
  const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost:5001" });
  const values = { window: dom.window, document: dom.window.document, IS_REACT_ACT_ENVIRONMENT: true };
  const previous = Object.keys(values).map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)] as const);
  for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { configurable:true, writable:true, value });
  let state = createWorkspaceFixture(), email = state.emails[0];
  const original = structuredClone(email);
  let dialogs!: ReturnType<typeof useEmailDialogs>;
  function Probe() { dialogs = useEmailDialogs(email); return null; }
  const root = createRoot(dom.window.document.getElementById("root")!);
  try {
    await act(async () => root.render(createElement(Probe)));
    await act(async () => { dialogs.openEdit(); dialogs.openApproval(); });
    state = saveEmail(state, email.id, email.revision, { body:"A newer message from another tab" });
    email = state.emails[0];
    await act(async () => root.render(createElement(Probe)));
    assert.equal(dialogs.editing?.revision, original.revision);
    assert.equal(dialogs.approving?.body, original.body);
    assert.throws(() => saveEmail(state, dialogs.editing!.id, dialogs.editing!.revision, { body:"Stale local draft" }), /changed/);
    assert.throws(() => approveEmail(state, dialogs.approving!.id, dialogs.approving!.revision), /changed/);
  } finally {
    await act(async () => root.unmount()); dom.window.close();
    for (const [key, descriptor] of previous) { if (descriptor) Object.defineProperty(globalThis,key,descriptor); else Reflect.deleteProperty(globalThis,key); }
  }
});
