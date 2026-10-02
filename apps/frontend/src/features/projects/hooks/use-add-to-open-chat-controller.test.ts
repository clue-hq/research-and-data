import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { ClueChatApiError } from "../data/chat-api";
import { addToChatFailureMessage } from "./use-add-to-chat-controller";

function source(path: string) {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}

const hook = source("./use-add-to-open-chat-controller.ts");
const surface = source("../../chat-shell/components/chat-surface.tsx");
const stage = source("../../chat-shell/components/artifact-stage.tsx");
const tab = source("../../accounts/components/project-target-accounts.tsx");

test("the in-chat add words a refusal exactly as the destination dialog does", () => {
  const stale = new ClueChatApiError("stale", { code: "CONTEXT_REF_STALE", status: 409, requestId: null });
  assert.match(addToChatFailureMessage(stale), /select them again/);
  assert.match(addToChatFailureMessage(new Error("boom")), /Your table selection is unchanged/);
});

test("the in-chat add runs the same server preparation as the global table, without a picker or navigation", () => {
  assert.match(hook, /repositories\.composerContext\.prepare\(/);
  assert.match(hook, /transport\.mode === "http"/);
  assert.doesNotMatch(hook, /router\.push|writeChatContextHandoff|sidebar\.list/);
});

test("the shell prepares against the open thread and lands the entities in its own composer", () => {
  assert.match(surface, /threadId: chat\.activeThreadId \?\? undefined/);
  assert.match(surface, /onAdded: controller\.addEntities/);
  assert.match(surface, /onFailed: controller\.failContextHandoff/);
  assert.match(surface, /addToOpenChat\.available && workspace\.composerCapabilities\.contextRefs/);
  assert.match(stage, /onAddToChat=\{onAddAccountsToChat\}/);
});

test("the tab's Add to chat is gated and limited like the global bar, clears only on acceptance, and is the black CTA", () => {
  assert.match(tab, /controller\.chatHandoffAvailable && data\.bulkCapabilities\.addToChat\.allowed/);
  assert.match(tab, /selectedCount > data\.bulkCapabilities\.addToChat\.maxItems/);
  assert.match(tab, /objectType: "account" as const, version: null/);
  assert.match(tab, /if \(accepted\) controller\.clearSelection\(\)/);
  // Founder 2026-09-11: on this tab the button is the filled (default) variant.
  const button = tab.match(/<Button disabled=\{overAddToChatLimit \|\| addingToChat\}[\s\S]*?>\s*\{addingToChat \? "Adding…" : "Add to chat"\}/)?.[0];
  assert.ok(button, "the Add to chat button");
  // The global bar's token (size md) in the filled default variant — no `variant=` prop.
  assert.match(button, /size="md" type="button"/);
  assert.doesNotMatch(button, /variant=/);
});
