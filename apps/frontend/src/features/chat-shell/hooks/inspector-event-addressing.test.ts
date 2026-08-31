import assert from "node:assert/strict";
import test from "node:test";
import { dispatchInspectorEvent } from "./use-inspector-controller";

// W3.1: the event seam grows write addressing — {selectionId, artifactId,
// documentVersion} ride every dispatched detail, additively (existing keys
// untouched). The hook plumbing is exercised through the exported dispatcher
// with a captured window (no DOM renderer in this repo's test setup).

interface Captured {
  type: string;
  detail: Record<string, unknown>;
}

function withCapturedWindow(run: () => void): Captured[] {
  const captured: Captured[] = [];
  const globals = globalThis as {
    window?: unknown;
    CustomEvent?: unknown;
  };
  const priorWindow = globals.window;
  const priorCustomEvent = globals.CustomEvent;
  class TestCustomEvent {
    type: string;
    detail: Record<string, unknown>;
    constructor(type: string, init: { detail: Record<string, unknown> }) {
      this.type = type;
      this.detail = init.detail;
    }
  }
  globals.CustomEvent = TestCustomEvent;
  globals.window = {
    dispatchEvent(event: TestCustomEvent) {
      captured.push({ detail: event.detail, type: event.type });
      return true;
    },
  };
  try {
    run();
  } finally {
    globals.window = priorWindow;
    globals.CustomEvent = priorCustomEvent;
  }
  return captured;
}

test("addressing rides the detail additively", () => {
  const events = withCapturedWindow(() => {
    dispatchInspectorEvent(
      "clue:inspector-property-change",
      { property: "fontSize", selectionType: "text", value: "18" },
      {
        artifactId: "doc_a",
        documentVersion: 7,
        selectionId: "headline",
      },
    );
  });
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "clue:inspector-property-change");
  assert.deepEqual(events[0].detail, {
    artifactId: "doc_a",
    documentVersion: 7,
    property: "fontSize",
    selectionId: "headline",
    selectionType: "text",
    value: "18",
  });
});

test("without addressing the detail is exactly the legacy shape", () => {
  const events = withCapturedWindow(() => {
    dispatchInspectorEvent("clue:inspector-action", {
      action: "more-actions",
      selectionType: "canvas",
    });
  });
  assert.deepEqual(events[0].detail, {
    action: "more-actions",
    selectionType: "canvas",
  });
});

test("null addressing values pass through as nulls (not addressable)", () => {
  const events = withCapturedWindow(() => {
    dispatchInspectorEvent(
      "clue:inspector-section-toggle",
      { open: true, section: "typography", selectionType: "text" },
      { artifactId: null, documentVersion: null, selectionId: null },
    );
  });
  assert.equal(events[0].detail.artifactId, null);
  assert.equal(events[0].detail.documentVersion, null);
  assert.equal(events[0].detail.selectionId, null);
});
