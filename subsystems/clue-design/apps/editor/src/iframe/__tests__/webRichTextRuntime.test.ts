import { afterEach, describe, expect, it } from "vitest";

import {
  mountRichTextEditor,
  renderRichTextDocument
} from "../webRichTextRuntime";

afterEach(() => {
  document.body.replaceChildren();
  window.getSelection()?.removeAllRanges();
});

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
      'Hello <span data-var="account.name" class="text-primary"><strong>Acme</strong></span><br /><a href="/pricing" target="_blank">pricing</a>'
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
});
