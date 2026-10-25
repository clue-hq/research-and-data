import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { createDirectMailFixture } from "../data/direct-mail.fixture";
import { approveMailers, updateMailer, type MailerPatch } from "../model/direct-mail";
import type { DirectMailController } from "./use-direct-mail";
import { useMailerEditor } from "./use-mailer-editor";

async function editorHarness(index: number, delayed = false) {
  const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost:5000" });
  const values = { window: dom.window, document: dom.window.document, sessionStorage: dom.window.sessionStorage, IS_REACT_ACT_ENVIRONMENT: true };
  const previous = Object.keys(values).map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)] as const);
  for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  let state = createDirectMailFixture();
  let saved = state.mailers[index];
  let editor!: ReturnType<typeof useMailerEditor>;
  let release!: () => void;
  const c = { data: state, run: async <T,>(operation: () => Promise<T>) => operation(), repository: {
    patch: async (id: string, revision: number, patch: MailerPatch) => {
      if (delayed) await new Promise<void>((resolve) => { release = resolve; });
      state = updateMailer(state, id, revision, patch); saved = state.mailers[index]; return state;
    },
  } } as unknown as DirectMailController;
  function Probe() { editor = useMailerEditor(c, saved); return null; }
  const root = createRoot(dom.window.document.getElementById("root")!);
  await act(async () => root.render(createElement(Probe)));
  return { editor: () => editor, state: () => state, finish: () => release(),
    rerender: () => root.render(createElement(Probe)),
    close: async () => { await act(async () => root.unmount()); dom.window.close(); for (const [key, descriptor] of previous) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else Reflect.deleteProperty(globalThis, key); } } };
}

test("editing a reviewed mailer invalidates the shared approval before leaving the editor", async () => {
  const h = await editorHarness(3);
  try {
    await act(async () => { await h.editor().edit({ note: "A newly edited note" }); });
    const record = h.state().mailers[3];
    assert.equal(record.stage, "needs_review");
    assert.equal(record.reviewedRevision, null);
    assert.equal(approveMailers(h.state(), [{ id: record.id, revision: record.revision }]).results[0].ok, false);
  } finally { await h.close(); }
});

test("typing during an outstanding save retains and rebases the newer draft", async () => {
  const h = await editorHarness(0, true);
  try {
    await act(async () => { h.editor().edit({ note: "First saved wording" }); });
    let save!: ReturnType<ReturnType<typeof useMailerEditor>["save"]>;
    await act(async () => { save = h.editor().save(); });
    await act(async () => { h.editor().edit({ note: "Later typing must survive" }); });
    await act(async () => { h.finish(); await save; h.rerender(); });
    assert.equal(h.state().mailers[0].note, "First saved wording");
    assert.equal(h.editor().mailer.note, "Later typing must survive");
    assert.equal(h.editor().dirty, true);
    assert.equal(h.editor().changedElsewhere, false);
    const recovery = JSON.parse(sessionStorage.getItem("clue-direct-mail-draft:mailer-avery")!);
    assert.equal(recovery.patch.note, "Later typing must survive");
    assert.equal(recovery.revision, h.state().mailers[0].revision);
  } finally { await h.close(); }
});
