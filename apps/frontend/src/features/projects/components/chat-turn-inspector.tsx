"use client";

import dynamic from "next/dynamic";
import type { TurnInspectorController } from "../hooks/use-turn-inspector";

/**
 * The dev-lens drawer's mount — deliberately almost empty.
 *
 * Everything the inspector actually is (four tabs, five Zod schemas, the body
 * renderers) lives in `chat-turn-inspector-panel.tsx` and is pulled in through
 * `next/dynamic`, so it is code-split into a chunk the browser fetches the first
 * time a developer opens the drawer. A production deployment never renders the
 * affordance that opens it — the capability probe 404s, because the routes were
 * never registered — so the chunk is never requested there.
 *
 * That is the cheap half of "keep the panel outside the production bundle path":
 * the code is not in the entry bundle. It is not a security boundary, and it is
 * not asked to be one — the boundary is the backend's startup refusal. This is
 * about not shipping a debugging tool's weight to people who cannot use it.
 *
 * `ssr: false` because there is nothing to prerender: the panel exists only in
 * response to a click, and its content is four authenticated reads.
 */
const Panel = dynamic(() => import("./chat-turn-inspector-panel"), { ssr: false });

export function ChatTurnInspector({
  inspector,
}: {
  inspector: TurnInspectorController;
}) {
  if (!inspector.available || inspector.turnId === null) return null;
  return <Panel inspector={inspector} />;
}
