import assert from "node:assert/strict";
import { test } from "node:test";
import { EDITOR_LABEL_PATTERN, editorLabelFor, editorLabelFromHost, editorOriginFor, sameRegistrableDomain } from "../src/editor-origin";

const LABEL = "aac8c47153e8e006ea26797aa03615b6"; // editorLabelFor("ws_123")

test("the label is the first 32 hex characters of sha256 over a versioned prefix", async () => {
  assert.equal(await editorLabelFor("ws_123"), LABEL);
  assert.equal(await editorLabelFor("ws_other"), "4e64151b7bc727c30d0cd033bcca9caa");
  assert.match(await editorLabelFor("ws_other"), EDITOR_LABEL_PATTERN);
});

test("a localhost suffix is http with its port; a real domain is https", () => {
  assert.equal(editorOriginFor(LABEL, "editor.localhost:3129"), `http://${LABEL}.editor.localhost:3129`);
  assert.equal(editorOriginFor(LABEL, "Edit.Example.com"), `https://${LABEL}.edit.example.com`);
  assert.throws(() => editorOriginFor("not-a-label", "edit.example.com"));
  assert.throws(() => editorOriginFor(LABEL, "https://edit.example.com"));
});

test("the label is read back from a Host header only under the configured suffix", () => {
  assert.equal(editorLabelFromHost(`${LABEL}.editor.localhost:3129`, "editor.localhost:3129"), LABEL);
  assert.equal(editorLabelFromHost(`${LABEL.toUpperCase()}.EDIT.EXAMPLE.COM`, "edit.example.com"), LABEL);
  assert.equal(editorLabelFromHost(`${LABEL}.editor.localhost:3130`, "editor.localhost:3129"), null);
  assert.equal(editorLabelFromHost(`x.${LABEL}.edit.example.com`, "edit.example.com"), null);
  assert.equal(editorLabelFromHost("edit.example.com", "edit.example.com"), null);
  assert.equal(editorLabelFromHost(undefined, "edit.example.com"), null);
});

// Review finding S2b-9 (and K3-8): the editor's domain must not be the app's registrable domain —
// code in the editor frame could then set cookies for the app — nor the published pages'. One rule,
// used by the editor server, the app's session route and (in Python) the production check.
test("two hosts share a registrable domain: the last two labels, or three under a two-level suffix", () => {
  assert.equal(sameRegistrableDomain("edit.deeppresence.ai", "app.cluehq.ai"), false);
  assert.equal(sameRegistrableDomain("edit.cluehq.ai", "app.cluehq.ai"), true);
  assert.equal(sameRegistrableDomain("cluehq.ai", "app.cluehq.ai"), true);
  assert.equal(sameRegistrableDomain("EDIT.ClueHQ.ai", "app.cluehq.ai:443"), true, "case and port do not matter");
  assert.equal(sameRegistrableDomain("edit.foo.co.uk", "app.foo.co.uk"), true);
  assert.equal(sameRegistrableDomain("edit.foo.co.uk", "app.bar.co.uk"), false, "co.uk is a public suffix");
  assert.equal(sameRegistrableDomain("editor.localhost:3129", "localhost:3029"), false, "dev stacks: *.localhost");
});
