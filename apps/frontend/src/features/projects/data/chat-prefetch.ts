import type { ChatRepositories } from "./chat-repositories";

/**
 * A chat's first reads, started before the chat view exists (chat load speed, 2026-10-15).
 *
 * Opening a chat used to wait for the project read (~0.8 s) before the chat view even mounted
 * and asked for anything. The project loader now starts the chat's reads — the project's chat
 * list and this chat's messages, turns and approval cards — at the same moment as the project
 * read, and puts them here; the chat controller takes them when it mounts instead of asking
 * again. Nothing here applies a read: the controller still shows the conversation only when the
 * chat list confirms this chat belongs to the project.
 *
 * Every promise carries a handler from the start, so reads nobody takes — the user navigated
 * away, the project read failed — never surface as unhandled rejections; a taken read still
 * rejects where it is awaited, exactly like a fresh request. Entries are taken once and expire
 * after a few seconds, so a later visit never uses old data.
 */

/** One chat's conversation reads (messages, turns, approval cards). */
export interface ConversationReads {
  messages: ReturnType<ChatRepositories["messages"]["list"]>;
  turns: ReturnType<ChatRepositories["turns"]["list"]>;
  gates: ReturnType<ChatRepositories["gates"]["list"]>;
}

export interface ChatPrefetch {
  threads: ReturnType<ChatRepositories["threads"]["list"]>;
  conversation: ConversationReads;
}

const TTL_MS = 10_000;
const store = new Map<string, { startedAt: number; prefetch: ChatPrefetch }>();

const keyOf = (projectId: string, threadId: string) => `${projectId}\u0000${threadId}`;

function handled<T>(promise: Promise<T>): Promise<T> {
  void promise.catch(() => undefined);
  return promise;
}

/** Start one chat's conversation reads, with a handler attached to each. */
export function startConversationReads(
  repositories: ChatRepositories,
  projectId: string,
  threadId: string,
): ConversationReads {
  return {
    messages: handled(repositories.messages.list({ projectId, threadId, includeBodies: true })),
    turns: handled(repositories.turns.list({ projectId, threadId })),
    gates: handled(repositories.gates.list({ projectId, threadId })),
  };
}

/** Start a chat's first reads unless a fresh set for the same chat is already running. */
export function startChatPrefetch(
  repositories: ChatRepositories,
  projectId: string,
  threadId: string,
  now: number = Date.now(),
): void {
  for (const [key, entry] of store) {
    if (now - entry.startedAt > TTL_MS) store.delete(key);
  }
  const key = keyOf(projectId, threadId);
  if (store.has(key)) return;
  store.set(key, {
    startedAt: now,
    prefetch: {
      threads: handled(repositories.threads.list({ projectId })),
      conversation: startConversationReads(repositories, projectId, threadId),
    },
  });
}

/** The chat's prefetched reads, once — or `null` when none were started or they are too old. */
export function takeChatPrefetch(
  projectId: string,
  threadId: string,
  now: number = Date.now(),
): ChatPrefetch | null {
  const key = keyOf(projectId, threadId);
  const entry = store.get(key);
  store.delete(key);
  if (!entry || now - entry.startedAt > TTL_MS) return null;
  return entry.prefetch;
}

export function clearChatPrefetch(): void {
  store.clear();
}
