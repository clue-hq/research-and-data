import assert from "node:assert/strict";
import test from "node:test";
import { cssFontString, typefacePreviewSpec } from "./typeface-preview";

const font = { id: "brand", family: "Brand font", source: "custom" as const };

test("selects an available normal face closest to regular weight without changing source order", () => {
  const faces = [
    { url: "/italic.woff2", weight: 400, style: "italic" as const },
    { url: "/bold.woff2", weight: 700, style: "normal" as const },
    { url: "/medium.woff2", weight: 500, style: "normal" as const },
  ];
  const preview = typefacePreviewSpec({ ...font, faces });
  assert.equal(preview.weight, 500);
  assert.equal(preview.style, "normal");
  assert.deepEqual(preview.sources, ['url("/medium.woff2")']);
  assert.equal(preview.registeredFamily, null);
  assert.equal(faces[0].url, "/italic.woff2");
});

test("an italic-only extraction uses the actual extracted style and weight", () => {
  const preview = typefacePreviewSpec({ ...font, faces: [{ url: "/bold-italic.woff2", weight: 700, style: "italic" }] });
  assert.equal(preview.style, "italic");
  assert.equal(preview.weight, 700);
});

test("font names and URLs cannot inject CSS or an HTML end tag", () => {
  const preview = typefacePreviewSpec({ ...font, previewFamily: 'Brand "font" </style>', faces: [{ url: 'https://example.com/font"name.woff2', weight: 400, style: "normal" }] });
  assert.equal(preview.family, 'Brand "font" </style>');
  assert.ok(!cssFontString(preview.family).includes("</style>"));
  assert.ok(preview.sources[0].includes("\\22 "));
});

test("unsourced faces must resolve an actual registered or locally installed font", () => {
  const preview = typefacePreviewSpec({ ...font, family: "Satoshi Variable" });
  assert.equal(preview.registeredFamily, '"Satoshi"');
  assert.deepEqual(preview.sources, ['local("Satoshi")']);
  assert.notEqual(preview.family, preview.registeredFamily);
  assert.notEqual(typefacePreviewSpec({ ...font, previewFamily: "kit-v1" }).family, typefacePreviewSpec({ ...font, previewFamily: "kit-v2" }).family);
});

test("preserves all captured files for a variant so script subsets remain available", () => {
  const faces = ["latin", "latin-ext"].map((script) => ({ url: `/${script}.woff2`, weight: 400, style: "normal" as const }));
  assert.deepEqual(typefacePreviewSpec({ ...font, faces: [...faces, faces[0]] }).sources, ['url("/latin.woff2")', 'url("/latin-ext.woff2")']);
});
