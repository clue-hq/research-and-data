import { describe, expect, it } from "vitest";
import { arrowNudge, isEditableEventTarget, keyboardArrangeAction, keyboardHistoryAction } from "../editorKeyboard";

function keyEvent(init: Partial<KeyboardEvent> & { key: string }): KeyboardEvent {
  return new KeyboardEvent("keydown", {
    key: init.key,
    metaKey: init.metaKey ?? false,
    ctrlKey: init.ctrlKey ?? false,
    shiftKey: init.shiftKey ?? false,
    altKey: init.altKey ?? false
  });
}

describe("editor keyboard helpers", () => {
  it("still resolves undo/redo (regression guard alongside the new arrange helper)", () => {
    expect(keyboardHistoryAction(keyEvent({ key: "z", metaKey: true }))).toBe("undo");
    expect(keyboardHistoryAction(keyEvent({ key: "z", metaKey: true, shiftKey: true }))).toBe("redo");
  });

  it("still resolves arrow nudges", () => {
    expect(arrowNudge("ArrowLeft")).toEqual({ x: -1, y: 0 });
    expect(arrowNudge("Enter")).toBeNull();
  });

  it("still detects editable event targets", () => {
    const input = document.createElement("input");
    expect(isEditableEventTarget(input)).toBe(true);
    expect(isEditableEventTarget(document.createElement("div"))).toBeFalsy();
  });

  describe("keyboardArrangeAction", () => {
    it("resolves ⌘G to group and ⌘⇧G to ungroup", () => {
      expect(keyboardArrangeAction(keyEvent({ key: "g", metaKey: true }))).toBe("group");
      expect(keyboardArrangeAction(keyEvent({ key: "G", metaKey: true, shiftKey: true }))).toBe("ungroup");
    });

    it("resolves ⌘] to forward and ⌥⌘] to front", () => {
      expect(keyboardArrangeAction(keyEvent({ key: "]", metaKey: true }))).toBe("forward");
      expect(keyboardArrangeAction(keyEvent({ key: "]", metaKey: true, altKey: true }))).toBe("to_front");
    });

    it("resolves ⌘[ to backward and ⌥⌘[ to back", () => {
      expect(keyboardArrangeAction(keyEvent({ key: "[", metaKey: true }))).toBe("backward");
      expect(keyboardArrangeAction(keyEvent({ key: "[", metaKey: true, altKey: true }))).toBe("to_back");
    });

    it("accepts ctrlKey as the modifier (non-Mac)", () => {
      expect(keyboardArrangeAction(keyEvent({ key: "g", ctrlKey: true }))).toBe("group");
    });

    it("returns null without a modifier or for unrelated keys", () => {
      expect(keyboardArrangeAction(keyEvent({ key: "g" }))).toBeNull();
      expect(keyboardArrangeAction(keyEvent({ key: "a", metaKey: true }))).toBeNull();
    });
  });
});
