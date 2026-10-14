import assert from "node:assert/strict";
import test from "node:test";
import { operatorSetupTarget } from "./operator-setup";

test("a workspace id and an http website make a target", () => {
  assert.deepEqual(
    operatorSetupTarget({ workspace: " ws_0123abcd ", website: " https://acme.example/x " }),
    { workspaceId: "ws_0123abcd", companyWebsite: "https://acme.example/x" },
  );
});

test("either parameter missing means no target", () => {
  assert.equal(operatorSetupTarget({ workspace: "ws_0123abcd" }), null);
  assert.equal(operatorSetupTarget({ website: "https://acme.example" }), null);
  assert.equal(operatorSetupTarget({}), null);
});

test("a malformed workspace id or website means no target", () => {
  for (const workspace of ["", "0123", "ws_", "ws_../x", "ws_a b"]) {
    assert.equal(operatorSetupTarget({ workspace, website: "https://acme.example" }), null);
  }
  for (const website of [
    "acme.example",
    "https://acme",
    "https://acme .example",
    "javascript:alert(1)",
  ]) {
    assert.equal(operatorSetupTarget({ workspace: "ws_0123abcd", website }), null);
  }
});

test("a repeated parameter is ambiguous and means no target", () => {
  assert.equal(
    operatorSetupTarget({ workspace: ["ws_a1", "ws_b2"], website: "https://acme.example" }),
    null,
  );
});
