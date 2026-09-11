import assert from "node:assert/strict";
import test from "node:test";
import { typefacePreviewCss, typefacePreviewFamily } from "./typeface-preview";

test("font CSS registers each recorded face without exposing CSS or HTML delimiters", () => {
  const font = {
    id: "brand", family: "Brand font", source: "custom" as const,
    previewFamily: 'Brand "font" </style>',
    faces: [{ url: 'https://example.com/font"name.woff2', weight: 500, style: "italic" as const }],
  };
  const css = typefacePreviewCss([font]);
  assert.ok(css.includes(`font-family: ${typefacePreviewFamily(font)};`));
  assert.match(css, /font-weight: 500;/);
  assert.match(css, /font-style: italic;/);
  assert.ok(!css.includes("</style>"));
  assert.ok(css.includes("\\22 "));
  assert.equal(typefacePreviewCss([{ id: "system", family: "Georgia", source: "library" }]), "");
});
