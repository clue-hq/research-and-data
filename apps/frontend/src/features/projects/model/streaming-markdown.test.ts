import assert from "node:assert/strict";
import test from "node:test";
import {
  parseInline,
  parseStreamingMarkdown,
  safeStreamingPrefix,
} from "./streaming-markdown";

/**
 * The no-raw-syntax-flash property, proved at every split of a growing string.
 *
 * The interesting assertion is not that finished Markdown parses — it is that
 * *no prefix of it* ever renders its own delimiters as text.
 */

const DOC =
  "Looking at **both** accounts.\n\n" +
  "- OpenAI is hiring `platform` engineers\n" +
  "- Anthropic shipped an [enterprise tier](https://anthropic.com/enterprise)\n\n" +
  "## Next\n\nShall I take the *deep* pass?";

function renderedText(markdown: string, streaming: boolean): string {
  return parseStreamingMarkdown(markdown, { streaming })
    .map((block) => {
      if (block.type === "code") return block.value;
      if (block.type === "list") {
        return block.items
          .map((item) => item.inline.map((token) => token.value).join(""))
          .join(" ");
      }
      return block.inline.map((token) => token.value).join("");
    })
    .join("\n");
}

test("no streamed prefix ever renders a Markdown delimiter as text", () => {
  for (let length = 0; length <= DOC.length; length += 1) {
    const rendered = renderedText(DOC.slice(0, length), true);
    assert.equal(
      /\*|`|\[|\]\(/.test(rendered),
      false,
      `prefix of length ${length} leaked syntax: ${JSON.stringify(rendered)}`,
    );
  }
});

test("the safe prefix withholds exactly the unfinished token", () => {
  assert.equal(safeStreamingPrefix("I found **two"), "I found ");
  assert.equal(safeStreamingPrefix("I found **two strong**"), "I found **two strong**");
  assert.equal(safeStreamingPrefix("run `npm ins"), "run ");
  assert.equal(safeStreamingPrefix("see [the doc](https://ex"), "see ");
  assert.equal(
    safeStreamingPrefix("see [the doc](https://example.com) now"),
    "see [the doc](https://example.com) now",
  );
  assert.equal(safeStreamingPrefix("a *partial"), "a ");
  assert.equal(safeStreamingPrefix("an _underscore"), "an ");
});

test("a completed document renders every construct", () => {
  const blocks = parseStreamingMarkdown(DOC);
  assert.deepEqual(
    blocks.map((block) => block.type),
    ["paragraph", "list", "heading", "paragraph"],
  );
  const list = blocks[1];
  assert.equal(list.type === "list" && list.ordered, false);
  assert.equal(list.type === "list" && list.items.length, 2);
  assert.equal(blocks[2].type === "heading" && blocks[2].level, 2);
});

test("block keys are stable as the document grows, so blocks update rather than remount", () => {
  const early = parseStreamingMarkdown(DOC.slice(0, 40), { streaming: true });
  const later = parseStreamingMarkdown(DOC, { streaming: false });
  assert.equal(early[0].key, later[0].key);
});

test("an unclosed code fence renders as code, never as three backticks", () => {
  const blocks = parseStreamingMarkdown("```ts\nconst a = 1;", { streaming: true });
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].type, "code");
  assert.equal(blocks[0].type === "code" && blocks[0].language, "ts");
  assert.equal(blocks[0].type === "code" && blocks[0].value, "const a = 1;");
});

test("ordered lists, quotes and inline code parse as themselves", () => {
  const blocks = parseStreamingMarkdown(
    "> a quote\n\n1. first\n2. second\n\nrun `make check`",
  );
  assert.deepEqual(
    blocks.map((block) => block.type),
    ["quote", "list", "paragraph"],
  );
  assert.equal(blocks[1].type === "list" && blocks[1].ordered, true);
  const inline = blocks[2].type === "paragraph" ? blocks[2].inline : [];
  assert.equal(inline.at(-1)?.type, "code");
});

test("inline parsing keeps text around each construct", () => {
  assert.deepEqual(parseInline("a **b** c"), [
    { type: "text", value: "a " },
    { type: "strong", value: "b" },
    { type: "text", value: " c" },
  ]);
});
