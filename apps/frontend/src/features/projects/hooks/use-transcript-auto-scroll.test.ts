import assert from "node:assert/strict";
import test from "node:test";
import { scrollMessageToTop } from "./use-transcript-auto-scroll";

/**
 * The reading-anchor scroll must move the transcript's own scroll container and nothing else.
 *
 * `element.scrollIntoView` walks every ancestor and scrolls whichever it needs; an ancestor
 * with `overflow: hidden` is still scrollable programmatically. On the live chat (2026-09-16)
 * that scrolled the chat pane itself — the header slid out of view and the composer rode up
 * with every message until a refresh. The helper computes the target from the element's
 * position inside the container and calls the container's `scrollTo`, so no ancestor can move.
 */

function fakeContainer(scrollTop: number, top: number) {
  const calls: Array<{ top: number; behavior: string }> = [];
  return {
    calls,
    container: {
      scrollTop,
      getBoundingClientRect: () => ({ top }),
      scrollTo: (options: { top: number; behavior: string }) => {
        calls.push(options);
      },
    },
  };
}

test("scrolls the container so the message sits at its top, minus the scroll padding", () => {
  const { container, calls } = fakeContainer(600, 50);
  const element = {
    getBoundingClientRect: () => ({ top: 410 }),
    scrollIntoView: () => {
      throw new Error("must never reach ancestors");
    },
  };
  scrollMessageToTop(container, element, { paddingTop: 16, behavior: "auto" });
  // element sits at 410 - 50 + 600 = 960 inside the container; 16px of scroll padding above it.
  assert.deepEqual(calls, [{ top: 944, behavior: "auto" }]);
});

test("never asks for a negative offset when the message is already near the top", () => {
  const { container, calls } = fakeContainer(0, 50);
  const element = {
    getBoundingClientRect: () => ({ top: 58 }),
    scrollIntoView: () => {
      throw new Error("must never reach ancestors");
    },
  };
  scrollMessageToTop(container, element, { paddingTop: 16, behavior: "smooth" });
  assert.deepEqual(calls, [{ top: 0, behavior: "smooth" }]);
});
