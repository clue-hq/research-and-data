/** The header menu's Undo/Redo arrive as the `clue:artifact-action-request` window event
 * (`use-artifact-action-menu-controller.ts`); the site lane answers only its own kind. */
export function siteHistoryActionFromEvent(detail: unknown): "undo" | "redo" | null {
  const value = detail as { action?: unknown; kind?: unknown } | null;
  if (!value || value.kind !== "site") return null;
  return value.action === "undo" || value.action === "redo" ? value.action : null;
}

/** Ruling: undo is the server's stack. A step is offered when the stack has one and no design
 * agent is at work on the document (the agent-run lock). */
export function siteHistoryDisabled({ depth, locked }: { depth: number; locked: boolean }): boolean {
  return locked || depth === 0;
}
