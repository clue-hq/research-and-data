// Plan 2, Task 5: the editor's rich text field keeps exactly the grammar — a stored styled span and a
// link survive a round trip through TipTap's schema — and text typed straight into a clone's slot is
// read back as the grammar's markup.
import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { generateHTML, generateJSON } from "@tiptap/html";
import { Bold } from "@tiptap/extension-bold";
import { Document } from "@tiptap/extension-document";
import { HardBreak } from "@tiptap/extension-hard-break";
import { Italic } from "@tiptap/extension-italic";
import { Paragraph } from "@tiptap/extension-paragraph";
import { Strike } from "@tiptap/extension-strike";
import { Text } from "@tiptap/extension-text";
import { Underline } from "@tiptap/extension-underline";
import { RICH_TEXT_EXTENSIONS, RICH_TEXT_OPTIONS, richFromDom, richTextField } from "../src/editor/rich-text";
import { normalizeRich } from "../src/rich";

// Puck's rich text with RICH_TEXT_OPTIONS registers these (its link replaced by ours).
const extensions = [Document, Paragraph, Text, Bold, Italic, Underline, Strike, HardBreak, ...RICH_TEXT_EXTENSIONS];
const roundTrip = (html: string) => normalizeRich(generateHTML(generateJSON(html, extensions), extensions));

test("the field is Puck's richtext, edited in place, with no menu of its own and no block or link pieces of Puck's", () => {
  const field = richTextField("Heading");
  assert.equal(field.type, "richtext");
  assert.equal(field.contentEditable, true);
  assert.equal(field.renderInlineMenu(), null);
  for (const piece of ["heading", "bulletList", "orderedList", "listItem", "codeBlock", "blockquote", "link"]) {
    assert.equal((RICH_TEXT_OPTIONS as Record<string, unknown>)[piece], false, piece);
  }
});

test("styled spans, links, marks and line breaks survive the editor's schema", () => {
  for (const html of [
    'Top <span data-s="heading~1">providers</span> win',
    'See <a href="/analysis" data-new-tab="">the analysis</a>',
    '<a href="https://x.com"><span data-s="body~2"><strong>all</strong></span></a> of it',
    "one<br>two <em>three</em> <u>four</u> <s>five</s>",
  ]) {
    assert.equal(roundTrip(html), html, html);
  }
});

test("what the grammar refuses is dropped by the editor, never kept: a javascript link, a bad key", () => {
  assert.equal(roundTrip('<a href="javascript:alert(1)">x</a>'), "x");
  assert.equal(roundTrip('<span data-s="a b">x</span>'), "x");
});

test("pasted paragraphs keep every word and are saved as one paragraph with line breaks", () => {
  assert.equal(roundTrip("<p>one</p><p>two <strong>three</strong></p>"), "one<br>two <strong>three</strong>");
});

test("text typed into a clone's slot is read as the grammar's markup", () => {
  const dom = new JSDOM("<!doctype html><body></body>");
  const slot = dom.window.document.createElement("h1");
  slot.innerHTML = 'Top <b>bold</b> <i>it</i><div>next line</div><span class="x">kept words</span> <a href="/a" data-new-tab="">l</a> <span data-s="0~1">s</span><br><script>x</script>';
  assert.equal(
    normalizeRich(richFromDom(slot)),
    'Top <strong>bold</strong> <em>it</em><br>next linekept words <a href="/a" data-new-tab="">l</a> <span data-s="0~1">s</span><br>',
  );
});
