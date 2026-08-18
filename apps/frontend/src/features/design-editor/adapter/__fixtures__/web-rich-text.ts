/**
 * W4.8a fixtures: REAL rich-text JSON harvested from a seeded web document,
 * exactly as `GET /documents/{id}` serves it under the `scene` key — NOT
 * hand-written shapes. Same discipline as `web-nodes.ts`.
 *
 * Harvest provenance: lane-C document `doc_c582718f5ceb4fb28cc5de7c5f8d44fb`
 * (workspace `ws_8040294627e146ae93f753ec0d3e1726`, lane design API
 * 127.0.0.1:8013), version 2, captured 2026-08-18.
 *
 * Two text nodes, deliberately:
 *   • `txtbody` — the **body** variant (`textVariantAllowsStructuredRichText`
 *     → structured: paragraphs + lists are available), carrying bold,
 *     italic+underline, strikethrough marks and one link range;
 *   • `txthead` — an `h1` variant, the NON-structured control (its rich-text
 *     session offers marks but no block controls).
 *
 * The same document also proved the commit op wire-true: a
 * `{kind:"set_rich_text", page_id:"home", id:"txtbody", content}` batch posted
 * with `intent:"rich_text_commit"` + `base_version` was accepted (200,
 * version 1 → 2) — the exact op `richTextCommitToOperation` builds.
 */
import type { RichTextDocument, WebNode } from "../../engine/webDocuments";

/** The seeded page's id — the value the commit adapter must resolve. */
export const RICH_TEXT_PAGE_ID = "home";

/** Structured (body-variant) node with marks and a link range. */
export const BODY_TEXT_NODE: WebNode = {
  id: "txtbody",
  kind: "text",
  classes: "text-base",
  variant: "body",
  content: {
    schema_version: 1,
    blocks: [
      {
        type: "paragraph",
        children: [
          { type: "text", text: "Lane C body copy with " },
          { type: "text", text: "bold", marks: { bold: true } },
          {
            type: "text",
            text: "italic underlined",
            marks: { italic: true, underline: true },
          },
          { type: "text", text: " plus a " },
          {
            type: "text",
            text: "linked phrase",
            link: { href: "https://example.com/lane-c", new_tab: true },
          },
          { type: "text", text: "." },
        ],
      },
      {
        type: "list",
        list_type: "unordered",
        items: [
          { children: [{ type: "text", text: "First bullet" }] },
          {
            children: [
              { type: "text", text: "Second bullet with " },
              { type: "text", text: "strike", marks: { strikethrough: true } },
            ],
          },
        ],
      },
    ],
  },
};

/** Non-structured (`h1`) control node. */
export const HEADLINE_TEXT_NODE: WebNode = {
  id: "txthead",
  kind: "text",
  classes: "text-4xl font-semibold",
  variant: "h1",
  content: {
    schema_version: 1,
    blocks: [
      {
        type: "paragraph",
        children: [{ type: "text", text: "Lane C headline" }],
      },
    ],
  },
};

/** The seeded page as `GET /documents/{id}` serves it. */
export const RICH_TEXT_PAGE: { page_root: string; nodes: Record<string, WebNode> } = {
  page_root: "root",
  nodes: {
    root: { id: "root", kind: "container", classes: "", children: ["secc"] },
    secc: { id: "secc", kind: "section", tag: "section", classes: "", children: ["boxc"] },
    boxc: {
      id: "boxc",
      kind: "container",
      classes: "flex flex-col gap-4",
      children: ["txthead", "txtbody"],
    },
    txthead: HEADLINE_TEXT_NODE,
    txtbody: BODY_TEXT_NODE,
  },
};

/** What the iframe session posts back on `rich-text-commit` for `txtbody`
 * after the user bolds the trailing period — the payload the commit adapter
 * turns into one `set_rich_text` op. */
export const BODY_COMMIT_CONTENT: RichTextDocument = {
  schema_version: 1,
  blocks: [
    {
      type: "paragraph",
      children: [
        { type: "text", text: "Lane C body copy with " },
        { type: "text", text: "bold", marks: { bold: true } },
        {
          type: "text",
          text: "italic underlined",
          marks: { italic: true, underline: true },
        },
        { type: "text", text: " plus a " },
        {
          type: "text",
          text: "linked phrase",
          link: { href: "https://example.com/lane-c", new_tab: true },
        },
        { type: "text", text: ".", marks: { bold: true } },
      ],
    },
  ],
};
