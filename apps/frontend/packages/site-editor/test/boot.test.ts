import assert from "node:assert/strict";
import { test } from "node:test";
import { readBootContext } from "../src/client/boot";

test("the frame boots only with a well-formed nonce and an exact app origin", () => {
  const nonce = "2f6c1a9e-7b44-4c0e-9a21-3d5e8f0b1c2a";
  assert.deepEqual(readBootContext(`#n=${nonce}`, "http://localhost:3029"), { appOrigin: "http://localhost:3029", nonce });
  assert.equal(readBootContext("#n=short", "http://localhost:3029"), null);
  assert.equal(readBootContext("", "http://localhost:3029"), null);
  assert.equal(readBootContext(`#n=${nonce}`, null), null);
  assert.equal(readBootContext(`#n=${nonce}`, "http://localhost:3029/path"), null);
  assert.equal(readBootContext(`#n=${nonce}`, "%APP_ORIGIN%"), null);
});
