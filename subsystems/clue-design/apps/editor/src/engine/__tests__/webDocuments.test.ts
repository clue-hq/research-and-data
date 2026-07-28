import { describe, expect, it } from "vitest";

import {
  buildWebButtonProps,
  isWebButtonCommandProps,
  listDialogComponents,
  webNodeButtonAction,
  type WebDoc,
  type WebNode
} from "../webDocuments";

function buttonNode(overrides: Partial<WebNode>): WebNode {
  return { id: "cta", kind: "button", classes: "", label: "Get started", variant: "primary", ...overrides };
}

describe("webNodeButtonAction", () => {
  it("reads the link form when no command is present", () => {
    expect(webNodeButtonAction(buttonNode({ href: "https://x.test" }))).toBe("link");
  });

  it("reads show_modal / close from the command form", () => {
    expect(webNodeButtonAction(buttonNode({ command: "show_modal", command_target: "d1" }))).toBe(
      "show_modal"
    );
    expect(webNodeButtonAction(buttonNode({ command: "close", command_target: "d1" }))).toBe(
      "close"
    );
  });

  it("falls back to link for an unknown command", () => {
    expect(webNodeButtonAction(buttonNode({ command: "bogus" }))).toBe("link");
  });
});

describe("buildWebButtonProps", () => {
  const common = {
    label: "Get started",
    variant: "secondary",
    href: "https://x.test",
    new_tab: true,
    command_target: "dialog-1"
  };

  it("builds the link form and preserves label + variant", () => {
    const props = buildWebButtonProps({ action: "link", ...common });
    expect(props).toEqual({
      kind: "button",
      label: "Get started",
      variant: "secondary",
      href: "https://x.test",
      new_tab: true
    });
    expect(isWebButtonCommandProps(props)).toBe(false);
  });

  it("builds the command form and preserves label + variant", () => {
    const open = buildWebButtonProps({ action: "show_modal", ...common });
    expect(open).toEqual({
      kind: "button",
      label: "Get started",
      variant: "secondary",
      command: "show_modal",
      command_target: "dialog-1"
    });
    expect(isWebButtonCommandProps(open)).toBe(true);

    const close = buildWebButtonProps({ action: "close", ...common });
    expect(close).toMatchObject({ command: "close", command_target: "dialog-1" });
  });

  it("round-trips link → command → link preserving label + variant", () => {
    const start = buttonNode({ href: "https://x.test", new_tab: false });
    const toCommand = buildWebButtonProps({
      action: "show_modal",
      label: start.label ?? "",
      variant: start.variant ?? "primary",
      href: start.href ?? "",
      new_tab: start.new_tab ?? false,
      command_target: "d9"
    });
    expect(toCommand).toMatchObject({ label: "Get started", variant: "primary" });

    const backToLink = buildWebButtonProps({
      action: "link",
      label: toCommand.label,
      variant: toCommand.variant,
      href: "https://x.test",
      new_tab: false,
      command_target: isWebButtonCommandProps(toCommand) ? toCommand.command_target : ""
    });
    expect(backToLink).toEqual({
      kind: "button",
      label: "Get started",
      variant: "primary",
      href: "https://x.test",
      new_tab: false
    });
  });
});

describe("listDialogComponents", () => {
  const doc: WebDoc = {
    pages: [
      {
        id: "home",
        name: "Home",
        route: "/",
        nodes: {
          hero: { id: "hero", kind: "section", classes: "" },
          d1: { id: "d1", kind: "component", classes: "", component: "dialog", name: "Signup" },
          acc: { id: "acc", kind: "component", classes: "", component: "accordion" },
          d2: { id: "d2", kind: "component", classes: "", component: "dialog" }
        }
      },
      {
        id: "about",
        name: "About",
        route: "/about",
        nodes: {
          d3: { id: "d3", kind: "component", classes: "", component: "dialog", name: "Contact" }
        }
      }
    ]
  };

  it("lists every dialog across pages, carrying the name when set", () => {
    const dialogs = listDialogComponents(doc);
    expect(dialogs).toEqual([
      { id: "d1", name: "Signup" },
      { id: "d2" },
      { id: "d3", name: "Contact" }
    ]);
  });

  it("returns an empty list for a null doc or one without dialogs", () => {
    expect(listDialogComponents(null)).toEqual([]);
    expect(
      listDialogComponents({
        pages: [{ id: "p", name: "P", route: "/", nodes: { t: { id: "t", kind: "text", classes: "" } } }]
      })
    ).toEqual([]);
  });
});
