import assert from "node:assert/strict";
import { test } from "node:test";
import { siteEditorStartupProblem } from "./startup-check";

// Review finding S7-2: a production app without CLUE_SITE_EDITOR_SUFFIX answered every site with
// "not configured" and logged nothing. The server now says so, loudly, when it starts.
test("S7-2: a production server without the editor domain says so at start-up", () => {
  assert.match(siteEditorStartupProblem({ NODE_ENV: "production" }) ?? "", /CLUE_SITE_EDITOR_SUFFIX/);
  assert.match(siteEditorStartupProblem({ NODE_ENV: "production", CLUE_SITE_EDITOR_SUFFIX: "  " }) ?? "", /CLUE_SITE_EDITOR_SUFFIX/);
  assert.equal(siteEditorStartupProblem({ NODE_ENV: "production", CLUE_SITE_EDITOR_SUFFIX: "edit.deeppresence.ai" }), null);
  assert.equal(siteEditorStartupProblem({ NODE_ENV: "development" }), null, "a dev server is not production");
});
