import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import test from "node:test";

test("MDXEditor and its node plugins resolve one Lexical instance", () => {
  const root = createRequire(resolve("package.json"));
  const editor = createRequire(root.resolve("@mdxeditor/editor"));
  const lexical = editor.resolve("lexical");
  for (const plugin of ["@lexical/react/LexicalHorizontalRuleNode", "@lexical/rich-text", "@lexical/list", "@lexical/markdown"]) {
    assert.equal(createRequire(editor.resolve(plugin)).resolve("lexical"), lexical, `${plugin} must share the editor's Lexical instance`);
  }
  assert.equal(editor.resolve("react"), root.resolve("react"));
});
