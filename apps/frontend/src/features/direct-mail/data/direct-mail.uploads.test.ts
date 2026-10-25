import assert from "node:assert/strict";
import test from "node:test";
import { registerHandwriting } from "./direct-mail.uploads";

test("unavailable handwriting reports a load failure instead of silently rendering a fallback", async () => {
  const previousDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
  const previousFont = Object.getOwnPropertyDescriptor(globalThis, "FontFace");
  Object.defineProperty(globalThis, "document", { configurable: true, value: { fonts: { add() {} } } });
  Object.defineProperty(globalThis, "FontFace", { configurable: true, value: class { async load() { throw new Error("Font unavailable"); } } });
  try {
    await assert.rejects(registerHandwriting([{ id: "missing", version: 1, name: "Missing style", family: "Missing", sourceUrl: "/missing.ttf", productionReady: true }]), /handwriting/i);
  } finally {
    if (previousDocument) Object.defineProperty(globalThis, "document", previousDocument); else Reflect.deleteProperty(globalThis, "document");
    if (previousFont) Object.defineProperty(globalThis, "FontFace", previousFont); else Reflect.deleteProperty(globalThis, "FontFace");
  }
});
