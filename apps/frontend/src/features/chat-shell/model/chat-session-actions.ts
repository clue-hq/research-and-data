export const CHAT_SESSION_ACTIONS = ["archive", "delete"] as const;

export type ChatSessionAction = (typeof CHAT_SESSION_ACTIONS)[number];
