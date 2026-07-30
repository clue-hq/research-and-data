import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  mountRichTextEditor,
  renderRichTextDocument,
  type RichTextSession
} from "../webRichTextRuntime";

const originalRangeBoundingRect = Range.prototype.getBoundingClientRect;

beforeEach(() => {
  // Lexical measures a collapsed caret after restoring focus. Browsers expose
  // Range#getBoundingClientRect, while jsdom deliberately has no layout.
  Range.prototype.getBoundingClientRect = () =>
    ({
      x: 0,
      y: 0,
      top: 0,
      right: 0,
      bottom: 0,
      left: 0,
      width: 0,
      height: 0,
      toJSON: () => ({})
    }) as DOMRect;
});

afterEach(() => {
  document.body.replaceChildren();
  window.getSelection()?.removeAllRanges();
  Range.prototype.getBoundingClientRect = originalRangeBoundingRect;
});

async function selectText(
  root: HTMLElement,
  value: string,
  start = 0,
  end = value.length
): Promise<Text> {
  const text = Array.from(root.querySelectorAll("[data-lexical-text]"))
    .flatMap((element) => Array.from(element.childNodes))
    .find(
      (node): node is Text =>
        node instanceof Text && node.data.includes(value)
    );
  expect(text).toBeDefined();
  const offset = text!.data.indexOf(value);
  const range = document.createRange();
  range.setStart(text!, offset + start);
  range.setEnd(text!, offset + end);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
  document.dispatchEvent(new Event("selectionchange"));
  await Promise.resolve();
  return text!;
}

function mount(initialHtml: string): {
  root: HTMLElement;
  session: RichTextSession;
} {
  const root = document.createElement("span");
  document.body.appendChild(root);
  return {
    root,
    session: mountRichTextEditor(root, { initialHtml })
  };
}

describe("web rich-text runtime", () => {
  it("renders the library-independent document without Lexical metadata", () => {
    const html = renderRichTextDocument({
      schema_version: 1,
      blocks: [
        {
          type: "paragraph",
          children: [
            { type: "text", text: "Hello " },
            {
              type: "variable",
              key: "account.name",
              fallback: "Acme",
              classes: "text-primary",
              marks: { bold: true }
            },
            { type: "line_break" },
            {
              type: "text",
              text: "pricing",
              link: { href: "/pricing", new_tab: true }
            }
          ]
        }
      ]
    });

    expect(html).toBe(
      'Hello <span data-var="account.name" class="text-primary"><strong>Acme</strong></span><br /><a href="/pricing" target="_blank" rel="noopener noreferrer">pricing</a>'
    );
    expect(html).not.toContain("lexical");
  });

  it("formats only the browser-selected range and preserves semantic metadata", async () => {
    const root = document.createElement("span");
    document.body.appendChild(root);
    const session = mountRichTextEditor(root, {
      initialHtml:
        'Hello <span data-var="account.name" class="text-primary">Acme</span> world'
    });
    await Promise.resolve();

    expect(root).toHaveAttribute("contenteditable", "true");
    expect(root).toHaveAttribute("role", "textbox");
    expect(root).toHaveAttribute("aria-multiline", "true");

    const textNodes = Array.from(root.querySelectorAll("[data-lexical-text]"))
      .flatMap((element) => Array.from(element.childNodes))
      .filter((node): node is Text => node.nodeType === Node.TEXT_NODE);
    const world = textNodes.find((node) => node.data.includes("world"));
    expect(world).toBeDefined();

    const range = document.createRange();
    range.setStart(world!, world!.data.indexOf("world"));
    range.setEnd(world!, world!.data.indexOf("world") + "world".length);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    await Promise.resolve();

    session.format("bold");
    const result = session.getDocument();
    expect(renderRichTextDocument(result)).toBe(
      'Hello <span data-var="account.name" class="text-primary">Acme</span> <strong>world</strong>'
    );
    session.destroy();
    expect(root).not.toHaveAttribute("contenteditable");
  });

  it("handles a formatting keyboard shortcut exactly once", async () => {
    const root = document.createElement("span");
    document.body.appendChild(root);
    const session = mountRichTextEditor(root, {
      initialHtml: "Format only these words"
    });
    await Promise.resolve();

    const text = root.querySelector("[data-lexical-text]")?.firstChild as Text;
    const range = document.createRange();
    range.setStart(text, 0);
    range.setEnd(text, "Format".length);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    await Promise.resolve();

    root.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "b",
        metaKey: true,
        bubbles: true,
        cancelable: true
      })
    );
    await Promise.resolve();

    expect(session.getHtml()).toBe("<strong>Format</strong> only these words");
    session.destroy();
  });

  it("applies only resolved theme class facets to the exact selected range", async () => {
    const { root, session } = mount(
      '<span class="text-lg text-primary bg-card">Hello world</span>'
    );
    await Promise.resolve();
    await selectText(root, "world");

    session.command({
      type: "set_class_facet",
      facet: "text_color",
      token: "accent",
      knownTokens: ["primary", "accent", "card"]
    });

    expect(session.getHtml()).toBe(
      '<span class="text-lg text-primary bg-card">Hello </span><span class="text-lg bg-card text-accent">world</span>'
    );
    session.destroy();
  });

  it("keeps the reported range alive while parent toolbar controls own focus", async () => {
    const { root, session } = mount("Keep this selection alive");
    await Promise.resolve();
    await selectText(root, "this selection");
    await new Promise<void>((resolve) =>
      window.requestAnimationFrame(() => resolve())
    );
    expect(session.getSelectionState().selectedText).toBe("this selection");

    session.setInteractionActive(true);
    window.getSelection()?.removeAllRanges();
    session.command({ type: "format", format: "italic" });

    expect(session.getHtml()).toBe(
      "Keep <em>this selection</em> alive"
    );
    session.destroy();
  });

  it("creates, edits, and removes links without losing surrounding marks", async () => {
    const { root, session } = mount("<strong>Read this story</strong>");
    await Promise.resolve();
    await selectText(root, "this story");

    session.command({
      type: "set_link",
      href: "/story",
      newTab: true
    });
    expect(session.getHtml()).toBe(
      '<strong>Read </strong><a href="/story" target="_blank" rel="noopener noreferrer"><strong>this story</strong></a>'
    );

    await selectText(root, "this story", 2, 2);
    session.command({
      type: "set_link",
      href: "https://example.com/story",
      newTab: false
    });
    expect(session.getHtml()).toContain(
      '<a href="https://example.com/story"><strong>this story</strong></a>'
    );
    expect(session.getSelectionState().link.state).toBe("on");

    session.command({ type: "remove_link" });
    expect(session.getHtml()).toBe("<strong>Read this story</strong>");
    session.destroy();
  });

  it("inserts a typed variable and requires semantic fallback content", async () => {
    const { root, session } = mount("Hello customer");
    await Promise.resolve();
    await selectText(root, "customer");

    session.command({
      type: "insert_variable",
      key: "account.name",
      fallback: "Customer"
    });
    expect(session.getDocument().blocks[0]).toEqual({
      type: "paragraph",
      children: [
        { type: "text", text: "Hello " },
        { type: "variable", key: "account.name", fallback: "Customer" }
      ]
    });
    session.destroy();
  });

  it("clears visual formatting while preserving links and variable semantics", async () => {
    const { root, session } = mount(
      '<a href="/account"><span data-var="account.name" class="text-primary bg-accent"><strong><em>Acme</em></strong></span></a>'
    );
    await Promise.resolve();
    await selectText(root, "Acme");

    session.command({ type: "clear_formatting" });
    expect(session.getHtml()).toBe(
      '<a href="/account"><span data-var="account.name">Acme</span></a>'
    );
    session.destroy();
  });

  it("treats a personalization variable as one atom when partially formatted", async () => {
    const { root, session } = mount(
      'Meet <span data-var="account.name">Acme</span>'
    );
    await Promise.resolve();
    await selectText(root, "Acme", 1, 3);

    session.command({ type: "format", format: "bold" });
    expect(session.getHtml()).toBe(
      'Meet <span data-var="account.name"><strong>Acme</strong></span>'
    );
    const block = session.getDocument().blocks[0];
    expect(block.type === "paragraph" ? block.children : []).toHaveLength(2);
    session.destroy();
  });

  it("reports a collapsed caret inside a link as an editable link context", async () => {
    const states: ReturnType<RichTextSession["getSelectionState"]>[] = [];
    const root = document.createElement("span");
    document.body.appendChild(root);
    const session = mountRichTextEditor(root, {
      initialHtml: '<a href="/old">linked words</a>',
      onSelectionStateChange: (state) => states.push(state)
    });
    await Promise.resolve();
    await selectText(root, "linked words", 3, 3);
    const state = session.getSelectionState();
    expect(state.collapsed).toBe(true);
    expect(state.link).toEqual({
      state: "on",
      href: "/old",
      newTab: false
    });
    expect(states.length).toBeGreaterThan(0);
    session.destroy();
  });
});
