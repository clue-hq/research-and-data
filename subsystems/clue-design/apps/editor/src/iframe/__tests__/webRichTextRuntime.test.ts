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
    session: mountRichTextEditor(root, { initialHtml, textVariant: "h2" })
  };
}

function mountStructured(initialHtml: string): {
  root: HTMLElement;
  session: RichTextSession;
} {
  const root = document.createElement("div");
  document.body.appendChild(root);
  return {
    root,
    session: mountRichTextEditor(root, {
      initialHtml,
      textVariant: "body"
    })
  };
}

function paste(
  root: HTMLElement,
  payload: { html?: string; plain?: string }
): void {
  const event = new Event("paste", {
    bubbles: true,
    cancelable: true
  }) as ClipboardEvent;
  Object.defineProperty(event, "clipboardData", {
    value: {
      getData(type: string) {
        return type === "text/html" ? payload.html ?? "" : payload.plain ?? "";
      }
    }
  });
  root.dispatchEvent(event);
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
      '<p>Hello <span data-var="account.name" class="text-primary"><strong>Acme</strong></span><br /><a href="/pricing" target="_blank" rel="noopener noreferrer">pricing</a></p>'
    );
    expect(html).not.toContain("lexical");
  });

  it("formats only the browser-selected range and preserves semantic metadata", async () => {
    const root = document.createElement("span");
    document.body.appendChild(root);
    const session = mountRichTextEditor(root, {
      initialHtml:
        'Hello <span data-var="account.name" class="text-primary">Acme</span> world',
      textVariant: "h2"
    });
    await Promise.resolve();

    expect(root).toHaveAttribute("contenteditable", "true");
    expect(root).toHaveAttribute("role", "textbox");
    expect(root).toHaveAttribute("aria-multiline", "false");

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
      '<p>Hello <span data-var="account.name" class="text-primary">Acme</span> <strong>world</strong></p>'
    );
    session.destroy();
    expect(root).not.toHaveAttribute("contenteditable");
  });

  it("handles a formatting keyboard shortcut exactly once", async () => {
    const root = document.createElement("span");
    document.body.appendChild(root);
    const session = mountRichTextEditor(root, {
      initialHtml: "Format only these words",
      textVariant: "h2"
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
      textVariant: "h2",
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

  it("round-trips semantic paragraphs and bounded nested lists", async () => {
    const { root, session } = mountStructured(
      "<p>Intro <strong>copy</strong></p>" +
        "<ul><li>First<ul><li>Nested <em>item</em></li></ul></li><li>Second</li></ul>" +
        "<p>Outro<br />line</p>"
    );
    await Promise.resolve();

    expect(root).toHaveAttribute("aria-multiline", "true");
    expect(session.getDocument()).toEqual({
      schema_version: 1,
      blocks: [
        {
          type: "paragraph",
          children: [
            { type: "text", text: "Intro " },
            { type: "text", text: "copy", marks: { bold: true } }
          ]
        },
        {
          type: "list",
          list_type: "unordered",
          items: [
            {
              children: [{ type: "text", text: "First" }],
              nested: [
                {
                  type: "list",
                  list_type: "unordered",
                  items: [
                    {
                      children: [
                        { type: "text", text: "Nested " },
                        { type: "text", text: "item", marks: { italic: true } }
                      ]
                    }
                  ]
                }
              ]
            },
            { children: [{ type: "text", text: "Second" }] }
          ]
        },
        {
          type: "paragraph",
          children: [
            { type: "text", text: "Outro" },
            { type: "line_break" },
            { type: "text", text: "line" }
          ]
        }
      ]
    });
    expect(session.getHtml()).toBe(
      "<p>Intro <strong>copy</strong></p>" +
        "<ul><li>First<ul><li>Nested <em>item</em></li></ul></li><li>Second</li></ul>" +
        "<p>Outro<br />line</p>"
    );
    session.destroy();
  });

  it("converts paragraph and list blocks without losing inline marks", async () => {
    const { root, session } = mountStructured(
      "<p><strong>First item</strong></p><p><em>Second paragraph</em></p>"
    );
    await Promise.resolve();
    await selectText(root, "First item");

    session.command({ type: "set_block", block: "unordered_list" });
    expect(session.getDocument().blocks).toEqual([
      {
        type: "list",
        list_type: "unordered",
        items: [
          {
            children: [
              { type: "text", text: "First item", marks: { bold: true } }
            ]
          }
        ]
      },
      {
        type: "paragraph",
        children: [
          { type: "text", text: "Second paragraph", marks: { italic: true } }
        ]
      }
    ]);

    session.command({ type: "set_block", block: "ordered_list" });
    expect(session.getDocument().blocks[0]).toMatchObject({
      type: "list",
      list_type: "ordered"
    });
    expect(session.getHtml()).toContain("<strong>First item</strong>");
    session.destroy();
  });

  it("preserves the final character when converting a caret-ended paragraph", async () => {
    const { root, session } = mountStructured(
      "<p>Browser-created paragraph<br />Line after break</p>"
    );
    await Promise.resolve();
    await selectText(
      root,
      "Line after break",
      "Line after break".length,
      "Line after break".length
    );
    await new Promise<void>((resolve) =>
      window.requestAnimationFrame(() => resolve())
    );

    // A parent toolbar pointer-down is delivered asynchronously after focus
    // has started moving out of the sandbox. The session must use the stable
    // selection captured above, not a browser focus-transfer side effect.
    window.getSelection()?.removeAllRanges();
    session.setInteractionActive(true);
    session.command({ type: "set_block", block: "ordered_list" });

    expect(session.getHtml()).toBe(
      "<ol><li>Browser-created paragraph<br />Line after break</li></ol>"
    );
    session.destroy();
  });

  it("uses Enter for blocks, Shift+Enter for a line break, and list Enter semantics", async () => {
    const paragraph = mountStructured("<p>First</p>");
    await Promise.resolve();
    await selectText(paragraph.root, "First", 5, 5);
    paragraph.root.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        cancelable: true
      })
    );
    expect(paragraph.session.getDocument().blocks).toHaveLength(2);
    paragraph.root.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        shiftKey: true,
        bubbles: true,
        cancelable: true
      })
    );
    expect(paragraph.session.getHtml()).toContain("<p><br /></p>");
    paragraph.session.destroy();

    const list = mountStructured("<ul><li>One</li></ul>");
    await Promise.resolve();
    await selectText(list.root, "One", 3, 3);
    list.root.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        cancelable: true
      })
    );
    expect(
      list.session.getDocument().blocks[0]
    ).toMatchObject({
      type: "list",
      items: [{ children: [{ text: "One" }] }, { children: [] }]
    });
    list.root.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        cancelable: true
      })
    );
    expect(list.session.getDocument().blocks.map((block) => block.type)).toEqual([
      "list",
      "paragraph"
    ]);
    list.session.destroy();
  });

  it("indents and outdents list items without exceeding valid nesting", async () => {
    const { root, session } = mountStructured(
      "<ul><li>One</li><li>Two</li></ul>"
    );
    await Promise.resolve();
    await selectText(root, "Two", 3, 3);
    expect(session.getSelectionState()).toMatchObject({
      blockType: "unordered_list",
      canIndent: true,
      canOutdent: false
    });

    root.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Tab",
        bubbles: true,
        cancelable: true
      })
    );
    expect(session.getDocument().blocks[0]).toMatchObject({
      type: "list",
      items: [
        {
          children: [{ text: "One" }],
          nested: [
            {
              type: "list",
              items: [{ children: [{ text: "Two" }] }]
            }
          ]
        }
      ]
    });
    expect(session.getSelectionState().canOutdent).toBe(true);

    root.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Tab",
        shiftKey: true,
        bubbles: true,
        cancelable: true
      })
    );
    expect(
      session.getDocument().blocks[0]
    ).toMatchObject({
      type: "list",
      items: [
        { children: [{ text: "One" }] },
        { children: [{ text: "Two" }] }
      ]
    });
    session.destroy();
  });

  it("normalizes multiline and rich paste into safe typed blocks", async () => {
    const plain = mountStructured("<p>Replace</p>");
    await Promise.resolve();
    await selectText(plain.root, "Replace");
    paste(plain.root, { plain: "One\nTwo\nThree" });
    expect(plain.session.getDocument().blocks).toEqual([
      { type: "paragraph", children: [{ type: "text", text: "One" }] },
      { type: "paragraph", children: [{ type: "text", text: "Two" }] },
      { type: "paragraph", children: [{ type: "text", text: "Three" }] }
    ]);
    plain.session.destroy();

    const rich = mountStructured("<p>Replace</p>");
    await Promise.resolve();
    await selectText(rich.root, "Replace");
    paste(rich.root, {
      html:
        '<p style="color:red" onclick="bad()">Safe<script>unsafe()</script>' +
        '<strong class="foreign"> bold</strong> ' +
        '<a href="javascript:alert(1)">bad link</a></p>' +
        "<ol><li>First</li><li>Second</li></ol>"
    });
    const html = rich.session.getHtml();
    expect(html).toBe(
      "<p>Safe<strong> bold</strong> bad link</p>" +
        "<ol><li>First</li><li>Second</li></ol>"
    );
    expect(html).not.toMatch(/style=|onclick=|javascript:|script|foreign/);
    rich.session.destroy();
  });
});
