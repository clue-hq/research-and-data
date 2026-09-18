import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  WorkspaceSwitcherProvider,
  useWorkspaceSwitcher,
} from "./workspace-switcher-context";

// The switcher lifted from the design build (def7344): a fixture-mode preview
// with three demo workspaces persisted in localStorage, and nothing at all in
// live mode, where the backend owns tenant switching at /select-workspace.

type Snapshot = ReturnType<typeof useWorkspaceSwitcher>;

function withDom(run: (dom: JSDOM) => Promise<void>) {
  return async () => {
    const dom = new JSDOM("<div id='root'></div>", { url: "http://localhost/" });
    const originals = new Map<string, PropertyDescriptor | undefined>();
    for (const [key, value] of Object.entries({
      window: dom.window,
      document: dom.window.document,
      navigator: dom.window.navigator,
      localStorage: dom.window.localStorage,
      Event: dom.window.Event,
      IS_REACT_ACT_ENVIRONMENT: true,
    })) {
      originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
      Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    }
    try {
      await run(dom);
    } finally {
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete (globalThis as Record<string, unknown>)[key];
      }
    }
  };
}

function mount(dom: JSDOM, demo: boolean, seen: Snapshot[]): Root {
  function Probe(): ReactNode {
    seen.push(useWorkspaceSwitcher());
    return null;
  }
  const root = createRoot(dom.window.document.getElementById("root")!);
  act(() => {
    root.render(
      createElement(WorkspaceSwitcherProvider, { demo }, createElement(Probe)),
    );
  });
  return root;
}

test(
  "demo mode offers three workspaces, selects one, persists it, and survives a remount",
  withDom(async (dom) => {
    const seen: Snapshot[] = [];
    const root = mount(dom, true, seen);
    const first = seen.at(-1)!;
    assert.equal(first.demo, true);
    assert.deepEqual(
      first.workspaces.map((workspace) => [workspace.id, workspace.role]),
      [["clue", "Admin"], ["acme", "Admin"], ["brightside", "Member"]],
    );
    assert.equal(first.activeWorkspace?.id, "clue");

    act(() => first.selectWorkspace("acme"));
    const selected = seen.at(-1)!;
    assert.equal(selected.activeWorkspace?.name, "Acme");
    assert.equal(selected.activeWorkspace?.initials, "A");
    assert.equal(dom.window.localStorage.getItem("clue:demo-workspace:v1"), "acme");

    act(() => selected.selectWorkspace("nope"));
    assert.equal(seen.at(-1)!.activeWorkspace?.id, "acme", "an unknown id is ignored");

    act(() => root.unmount());
    const remounted: Snapshot[] = [];
    const again = mount(dom, true, remounted);
    assert.equal(remounted.at(-1)!.activeWorkspace?.id, "acme", "the choice survives a reload");
    act(() => again.unmount());
  }),
);

test(
  "live mode offers no selection: the backend switches tenants, not the sidebar",
  withDom(async (dom) => {
    dom.window.localStorage.setItem("clue:demo-workspace:v1", "acme");
    const seen: Snapshot[] = [];
    const root = mount(dom, false, seen);
    const live = seen.at(-1)!;
    assert.equal(live.demo, false);
    assert.deepEqual(live.workspaces, []);
    assert.equal(live.activeWorkspace, null);
    act(() => live.selectWorkspace("clue"));
    assert.equal(dom.window.localStorage.getItem("clue:demo-workspace:v1"), "acme", "no write in live mode");
    act(() => root.unmount());
  }),
);
