import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { bodyAfterMarkdownChange, markdownCanSave } from "./markdown-session";

test("normalization and undo keep the original raw Markdown, including surrounding whitespace", () => {
  const raw = "\n# Heading\n\n* item\n";
  const normalized = "# Heading\n\n- item";
  assert.equal(bodyAfterMarkdownChange(raw, normalized, normalized), raw);
  assert.equal(bodyAfterMarkdownChange(raw, normalized, raw), raw);
  assert.equal(bodyAfterMarkdownChange(raw, normalized, "# Changed"), "# Changed");
});

test("source drafts and failed imports cannot be saved before successful visual validation", () => {
  assert.equal(markdownCanSave({ error: null, viewMode: "source" }), false);
  assert.equal(markdownCanSave({ error: "Import failed", viewMode: "rich-text" }), false);
  assert.equal(markdownCanSave({ error: null, viewMode: "rich-text" }), true);
});

test("MDXEditor, plugins and the existing design text runtime share one Lexical constructor", () => {
  const root = createRequire(import.meta.url);
  const mdx = createRequire(root.resolve("@mdxeditor/editor"));
  assert.equal(root.resolve("lexical"), mdx.resolve("lexical"));
  for (const plugin of ["@lexical/react/LexicalHorizontalRuleNode", "@lexical/rich-text", "@lexical/list", "@lexical/markdown", "@lexical/history"]) {
    assert.equal(createRequire(mdx.resolve(plugin)).resolve("lexical"), root.resolve("lexical"), plugin);
  }
  assert.equal(mdx.resolve("react"), root.resolve("react"));
});
