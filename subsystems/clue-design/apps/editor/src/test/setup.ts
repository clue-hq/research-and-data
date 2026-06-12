import "@testing-library/jest-dom/vitest";
import { TextDecoder, TextEncoder } from "node:util";

// jsdom does not ship TextEncoder/TextDecoder; the wasm-bindgen JS glue
// needs them to move strings across the WASM boundary. Use Node's.
if (typeof globalThis.TextEncoder === "undefined") {
  globalThis.TextEncoder = TextEncoder as typeof globalThis.TextEncoder;
}
if (typeof globalThis.TextDecoder === "undefined") {
  globalThis.TextDecoder = TextDecoder as unknown as typeof globalThis.TextDecoder;
}
