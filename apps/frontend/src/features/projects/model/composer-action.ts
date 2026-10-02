import type { ProjectComposerAttachment } from "./project-composer";

export function hasComposerDraft(
  prompt: string, entityIds: readonly string[], attachments: readonly ProjectComposerAttachment[],
): boolean {
  return Boolean(prompt.replace(/[\u200B\uFEFF]/g, "").trim()) ||
    entityIds.length > 0 || attachments.some((attachment) => attachment.status === "ready");
}

export function composerAction(input: {
  running: boolean; stopping: boolean; hasDraft: boolean;
  disabled: boolean; sendDisabled: boolean; submitting: boolean;
}): { kind: "send" | "stop"; disabled: boolean } {
  if (input.stopping) return { kind: "stop", disabled: true };
  if (input.running && !input.hasDraft) {
    return { kind: "stop", disabled: input.disabled || input.submitting };
  }
  return { kind: "send", disabled: input.disabled || input.sendDisabled || input.submitting || !input.hasDraft };
}
