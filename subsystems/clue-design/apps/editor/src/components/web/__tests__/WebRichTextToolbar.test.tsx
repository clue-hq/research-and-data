import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { WebRichTextToolbar } from "../WebRichTextToolbar";
import type { RichTextSelectionState } from "@/engine/webBridge";

const RANGE: RichTextSelectionState = {
  collapsed: false,
  selectedText: "selected words",
  rect: {
    x: 100,
    y: 120,
    top: 120,
    right: 240,
    bottom: 142,
    left: 100,
    width: 140,
    height: 22
  },
  formats: {
    bold: "on",
    italic: "mixed",
    underline: "off",
    strikethrough: "off"
  },
  commonClasses: ["text-primary"],
  mixedClasses: ["bg-accent"],
  link: { state: "off", href: null, newTab: null }
};

function setup(params?: {
  selection?: RichTextSelectionState;
  variables?: { key: string; label: string; example: string | null }[];
  disabled?: boolean;
}) {
  const iframe = document.createElement("iframe");
  vi.spyOn(iframe, "getBoundingClientRect").mockReturnValue({
    x: 20,
    y: 40,
    top: 40,
    left: 20,
    right: 820,
    bottom: 640,
    width: 800,
    height: 600,
    toJSON: () => ({})
  });
  const iframeRef = createRef<HTMLIFrameElement>();
  iframeRef.current = iframe;
  const command = vi.fn();
  const setInteractionActive = vi.fn();
  const settle = vi.fn();
  const result = render(
    <WebRichTextToolbar
      iframeRef={iframeRef}
      nodeId="headline"
      selection={params?.selection ?? RANGE}
      theme={{
        tokens: { primary: "var(--test-primary)", accent: "var(--test-accent)" },
        displayFamily: null,
        bodyFamily: null
      }}
      variables={params?.variables ?? []}
      disabled={params?.disabled ?? false}
      command={command}
      setInteractionActive={setInteractionActive}
      settle={settle}
    />
  );
  return { ...result, command, iframe, setInteractionActive, settle };
}

describe("WebRichTextToolbar", () => {
  it("renders only for a non-collapsed range or a caret inside a link", () => {
    const { rerender } = setup({
      selection: {
        ...RANGE,
        collapsed: true,
        selectedText: "",
        link: { state: "off", href: null, newTab: null }
      }
    });
    expect(
      screen.queryByRole("toolbar", { name: "Selected text formatting" })
    ).not.toBeInTheDocument();

    rerender(
      <WebRichTextToolbar
        iframeRef={{ current: document.createElement("iframe") }}
        nodeId="headline"
        selection={{
          ...RANGE,
          collapsed: true,
          selectedText: "",
          link: { state: "on", href: "/story", newTab: false }
        }}
        theme={null}
        variables={[]}
        disabled={false}
        command={vi.fn()}
        setInteractionActive={vi.fn()}
        settle={vi.fn()}
      />
    );
    expect(
      screen.getByRole("toolbar", { name: "Selected text formatting" })
    ).toBeInTheDocument();
  });

  it("reports active and mixed marks and sends one configured mark command", () => {
    const { command, setInteractionActive } = setup();
    expect(screen.getByRole("button", { name: "Bold" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByRole("button", { name: "Italic" })).toHaveAttribute(
      "aria-pressed",
      "mixed"
    );
    fireEvent.pointerDown(screen.getByRole("button", { name: "Underline" }));
    fireEvent.click(screen.getByRole("button", { name: "Underline" }));
    expect(setInteractionActive).toHaveBeenCalledWith("headline", true);
    expect(command).toHaveBeenCalledWith("headline", {
      type: "format",
      format: "underline"
    });
  });

  it("offers only resolved theme tokens for text and highlight colors", () => {
    const { command } = setup();
    const textColor = screen.getByRole("button", { name: "Text color" });
    const highlight = screen.getByRole("button", { name: "Highlight color" });
    expect(textColor).toHaveAttribute("aria-pressed", "true");
    expect(highlight).toHaveAttribute("aria-pressed", "mixed");

    fireEvent.click(textColor);
    fireEvent.click(screen.getByRole("button", { name: "Text color: accent" }));
    expect(command).toHaveBeenCalledWith("headline", {
      type: "set_class_facet",
      facet: "text_color",
      token: "accent",
      knownTokens: ["accent", "primary"]
    });

    fireEvent.click(screen.getByRole("button", { name: "Highlight color" }));
    fireEvent.click(screen.getByRole("button", { name: "Highlight color: primary" }));
    expect(command).toHaveBeenLastCalledWith("headline", {
      type: "set_class_facet",
      facet: "highlight",
      token: "primary",
      knownTokens: ["accent", "primary"]
    });
  });

  it("rejects unsafe links, applies safe links, and exposes unlink separately", () => {
    const { command, rerender } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Insert link" }));
    fireEvent.change(screen.getByLabelText("URL"), {
      target: { value: "javascript:alert(1)" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply link" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Use http(s)");
    expect(command).not.toHaveBeenCalledWith(
      "headline",
      expect.objectContaining({ type: "set_link" })
    );

    fireEvent.change(screen.getByLabelText("URL"), {
      target: { value: "/safe" }
    });
    fireEvent.click(screen.getByLabelText("Open in a new tab"));
    fireEvent.click(screen.getByRole("button", { name: "Apply link" }));
    expect(command).toHaveBeenCalledWith("headline", {
      type: "set_link",
      href: "/safe",
      newTab: true
    });

    rerender(
      <WebRichTextToolbar
        iframeRef={{ current: document.createElement("iframe") }}
        nodeId="headline"
        selection={{
          ...RANGE,
          link: { state: "on", href: "/safe", newTab: true }
        }}
        theme={null}
        variables={[]}
        disabled={false}
        command={command}
        setInteractionActive={vi.fn()}
        settle={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit link" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove link" }));
    expect(command).toHaveBeenCalledWith("headline", { type: "remove_link" });
  });

  it("disables variables without a catalog and inserts a typed variable with fallback", () => {
    const { rerender, command } = setup();
    expect(
      screen.getByRole("button", { name: "Insert personalization variable" })
    ).toBeDisabled();
    expect(
      screen.getByText("Add an account before inserting personalization variables.")
    ).toBeInTheDocument();

    rerender(
      <WebRichTextToolbar
        iframeRef={{ current: document.createElement("iframe") }}
        nodeId="headline"
        selection={RANGE}
        theme={null}
        variables={[
          { key: "account.name", label: "Name", example: "Acme" }
        ]}
        disabled={false}
        command={command}
        setInteractionActive={vi.fn()}
        settle={vi.fn()}
      />
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Insert personalization variable" })
    );
    fireEvent.change(screen.getByLabelText("Visible fallback"), {
      target: { value: "Customer" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Insert variable" }));
    expect(command).toHaveBeenCalledWith("headline", {
      type: "insert_variable",
      key: "account.name",
      fallback: "Customer"
    });
  });

  it("clears formatting semantically and Escape cancels the local session", () => {
    const { command, settle } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Clear formatting" }));
    expect(command).toHaveBeenCalledWith("headline", {
      type: "clear_formatting"
    });

    fireEvent.keyDown(
      screen.getByRole("toolbar", { name: "Selected text formatting" }),
      { key: "Escape" }
    );
    expect(settle).toHaveBeenCalledWith("headline", "cancel");
  });

  it("leaves ordinary keyboard focus traversal untrapped", () => {
    const { setInteractionActive, settle } = setup();
    const bold = screen.getByRole("button", { name: "Bold" });
    bold.focus();
    expect(setInteractionActive).toHaveBeenCalledWith("headline", true);
    const tab = new KeyboardEvent("keydown", {
      key: "Tab",
      bubbles: true,
      cancelable: true
    });
    bold.dispatchEvent(tab);
    expect(tab.defaultPrevented).toBe(false);
    expect(settle).not.toHaveBeenCalled();
  });

  it("releases or settles the edit after keyboard focus leaves the toolbar", async () => {
    const { iframe, setInteractionActive, settle } = setup();
    document.body.appendChild(iframe);
    const clear = screen.getByRole("button", { name: "Clear formatting" });
    clear.focus();
    setInteractionActive.mockClear();

    fireEvent.keyDown(clear, { key: "Tab" });
    iframe.focus();
    await waitFor(() =>
      expect(setInteractionActive).toHaveBeenCalledWith("headline", false)
    );
    expect(settle).not.toHaveBeenCalled();

    const outside = document.createElement("button");
    document.body.appendChild(outside);
    clear.focus();
    settle.mockClear();
    fireEvent.keyDown(clear, { key: "Tab", shiftKey: true });
    outside.focus();
    await waitFor(() =>
      expect(settle).toHaveBeenCalledWith("headline", "commit")
    );
    iframe.remove();
    outside.remove();
  });

  it("does not preserve the iframe selection for disabled controls", () => {
    const { setInteractionActive } = setup({ disabled: true });
    const bold = screen.getByRole("button", { name: "Bold" });
    fireEvent.pointerDown(bold);
    fireEvent.focus(bold);
    expect(setInteractionActive).not.toHaveBeenCalled();
  });
});
