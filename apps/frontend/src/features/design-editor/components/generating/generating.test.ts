import assert from "node:assert/strict";
import { it } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AdDesigningLock } from "./ad-designing-lock";
import { GeneratingGlow } from "./generating-glow";
import { sceneAgentMotionActive } from "./scene-agent-motion";

it("runs only while the lock is engaged over a real scene", () => {
  assert.equal(sceneAgentMotionActive({ agentWorking: true, hasScene: true }), true);
  assert.equal(sceneAgentMotionActive({ agentWorking: false, hasScene: true }), false);
  assert.equal(sceneAgentMotionActive({ agentWorking: undefined, hasScene: true }), false);
  assert.equal(sceneAgentMotionActive({ agentWorking: true, hasScene: false }), false);
});

it("the lock is a polite status carrying the Clue mark spinner and the approved copy", () => {
  const html = renderToStaticMarkup(createElement(AdDesigningLock, { active: true }));
  assert.match(html, /class="clue-gen-lock"/);
  assert.match(html, /data-active="true"/);
  assert.match(html, /data-placement="top-left"/);
  assert.match(html, /role="status"/);
  assert.match(html, /aria-live="polite"/);
  assert.equal((html.match(/<path /g) ?? []).length, 3, "three mark pieces, in order");
  assert.match(html, /class="clue-gen-spinner"/);
  assert.match(html, /Agent is designing\. Please wait\./);
});

it("an inactive lock stays mounted, hidden from assistive tech, and takes no input", () => {
  const html = renderToStaticMarkup(createElement(AdDesigningLock, { active: false }));
  assert.match(html, /data-active="false"/);
  assert.match(html, /aria-hidden="true"/);
});

it("the glow is four decorative layers and never a landmark", () => {
  const html = renderToStaticMarkup(createElement(GeneratingGlow, { active: true }));
  assert.match(html, /class="clue-gen-glow"/);
  assert.match(html, /aria-hidden="true"/);
  for (const layer of ["haze", "bloom", "line", "rim"]) {
    assert.match(html, new RegExp(`clue-gen-glow__${layer}`));
  }
});
