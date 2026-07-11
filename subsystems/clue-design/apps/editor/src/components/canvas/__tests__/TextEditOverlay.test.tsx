import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TextEditOverlay, type TextEditStyle } from "../TextEditOverlay";

const style: TextEditStyle = {
  fontFamily: "Inter",
  fontSize: 18,
  fontWeight: 600,
  align: "left",
  valign: "top",
  lineHeight: 1.2,
  letterSpacing: 0,
  color: "#27231d"
};

const base = {
  box: { x: 10, y: 20, width: 100, height: 40 },
  rotation: 0,
  content: "Hello",
  style,
  pageOrigin: { x: 100, y: 50 },
  zoom: 2
};

describe("TextEditOverlay (Wave 3 C4)", () => {
  it("seeds the content, focuses, and positions over the node in screen space", () => {
    const { getByTestId } = render(
      <TextEditOverlay {...base} onCommit={() => {}} onCancel={() => {}} />
    );
    const ta = getByTestId("text-edit-overlay") as HTMLTextAreaElement;
    expect(ta.value).toBe("Hello");
    expect(document.activeElement).toBe(ta);
    // left = pageOrigin.x + box.x*zoom = 100 + 20 = 120; top = 50 + 40 = 90.
    expect(ta.style.left).toBe("120px");
    expect(ta.style.top).toBe("90px");
    expect(ta.style.width).toBe("200px"); // 100 * 2
    expect(ta.style.fontSize).toBe("36px"); // 18 * 2
  });

  it("commits the edited value on blur", () => {
    const onCommit = vi.fn();
    const { getByTestId } = render(
      <TextEditOverlay {...base} onCommit={onCommit} onCancel={() => {}} />
    );
    const ta = getByTestId("text-edit-overlay") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "Edited text" } });
    fireEvent.blur(ta);
    expect(onCommit).toHaveBeenCalledWith("Edited text");
  });

  it("cancels on Escape without committing", () => {
    const onCommit = vi.fn();
    const onCancel = vi.fn();
    const { getByTestId } = render(
      <TextEditOverlay {...base} onCommit={onCommit} onCancel={onCancel} />
    );
    const ta = getByTestId("text-edit-overlay") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "changed" } });
    fireEvent.keyDown(ta, { key: "Escape" });
    fireEvent.blur(ta); // the cancel-driven blur must not also commit
    expect(onCancel).toHaveBeenCalled();
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("commits on Cmd/Ctrl+Enter", () => {
    const onCommit = vi.fn();
    const { getByTestId } = render(
      <TextEditOverlay {...base} onCommit={onCommit} onCancel={() => {}} />
    );
    const ta = getByTestId("text-edit-overlay") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "via shortcut" } });
    fireEvent.keyDown(ta, { key: "Enter", metaKey: true });
    expect(onCommit).toHaveBeenCalledWith("via shortcut");
  });

  it("rotates the overlay to match the node", () => {
    const { getByTestId } = render(
      <TextEditOverlay {...base} rotation={30} onCommit={() => {}} onCancel={() => {}} />
    );
    const ta = getByTestId("text-edit-overlay") as HTMLTextAreaElement;
    expect(ta.style.transform).toBe("rotate(30deg)");
    expect(ta.style.transformOrigin).toBe("top left");
  });
});
