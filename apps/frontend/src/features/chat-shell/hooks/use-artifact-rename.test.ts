import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { DocumentRenameError } from "../../design-editor/engine/scene/documentStore";
import { AGENT_RUN_LOCK_NOTE } from "../model/agent-run-lock";
import { useArtifactRename, type ArtifactRename } from "./use-artifact-rename";

// K1-5 (founder ruling 2026-10-16): a rename that loses the race to a design run is refused by the
// server with 409 `document.agent_run_active`. The tab keeps its old title (nothing is applied)
// and the lock's own sentence is what the person reads.

const dom = new JSDOM("<!doctype html><html><body></body></html>");
Object.assign(globalThis, { window: dom.window, document: dom.window.document });
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const agentRunRefusal = () =>
  new DocumentRenameError("refused", { status: 409, code: "document.agent_run_active" });

async function mount(rename: (documentId: string, title: string) => Promise<string>, locked = false) {
  let current: ArtifactRename | null = null;
  const renamed: Array<[string, string]> = [];
  function Probe({ locked: isLocked }: { locked: boolean }) {
    current = useArtifactRename({
      locked: isLocked,
      onRenamed: (artifactId, title) => renamed.push([artifactId, title]),
      rename,
    });
    return null;
  }
  const container = document.createElement("div");
  const root = createRoot(container);
  await act(async () => root.render(createElement(Probe, { locked })));
  return {
    get: () => current as unknown as ArtifactRename,
    renamed,
    setLocked: async (next: boolean) => act(async () => root.render(createElement(Probe, { locked: next }))),
    unmount: () => act(async () => root.unmount()),
  };
}

test("a rename refused because the agent is working applies nothing and says the lock's sentence", async () => {
  const probe = await mount(async () => {
    throw agentRunRefusal();
  });
  await act(async () => probe.get().rename("artifact-1", "Mid-run"));
  assert.deepEqual(probe.renamed, []);
  assert.deepEqual(probe.get().refusal, { artifactId: "artifact-1", note: AGENT_RUN_LOCK_NOTE });
  await probe.unmount();
});

test("any other refusal stays quiet, as before", async () => {
  const probe = await mount(async () => {
    throw new DocumentRenameError("finalized", { status: 409, code: "document.finalized" });
  });
  await act(async () => probe.get().rename("artifact-1", "Nope"));
  assert.deepEqual(probe.renamed, []);
  assert.equal(probe.get().refusal, null);
  await probe.unmount();
});

test("the note clears when the run lets go, and on the next rename that lands", async () => {
  let refuse = true;
  const probe = await mount(async (_documentId, title) => {
    if (refuse) throw agentRunRefusal();
    return title;
  });
  await act(async () => probe.get().rename("artifact-1", "Mid-run"));
  assert.notEqual(probe.get().refusal, null);
  // The run the server named engages the lock, then finishes: the sentence is no longer true.
  await probe.setLocked(true);
  assert.notEqual(probe.get().refusal, null);
  await probe.setLocked(false);
  assert.equal(probe.get().refusal, null);

  await act(async () => probe.get().rename("artifact-1", "Mid-run"));
  assert.notEqual(probe.get().refusal, null);
  refuse = false;
  await act(async () => probe.get().rename("artifact-1", "After"));
  assert.deepEqual(probe.renamed, [["artifact-1", "After"]]);
  assert.equal(probe.get().refusal, null);
  await probe.unmount();
});
