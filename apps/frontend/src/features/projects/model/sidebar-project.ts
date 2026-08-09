import { z } from "zod";
import { ThreadStatusSchema } from "./chat-thread";

/**
 * The sidebar's compact project/thread hierarchy.
 *
 * The conversation status is the pinned precedence vocabulary from
 * `chat-thread.ts` — one enum for the whole feature, so the sidebar badge and
 * the thread header can never disagree. The frontend proposal's `review` is
 * gone (no backend surface emits it) and `archived` is present (the backend
 * does emit it), which is charter §2's "the sidebar's five-status vocabulary
 * and the workspace's six-phase vocabulary never meet" being closed.
 */
export const SidebarConversationStatusSchema = ThreadStatusSchema;

export const SidebarConversationSchema = z.object({
  href: z.string().startsWith("/"),
  id: z.string().min(1),
  status: SidebarConversationStatusSchema.default("idle"),
  title: z.string().min(1),
});

export const SidebarProjectSchema = z.object({
  conversations: z.array(SidebarConversationSchema),
  expanded: z.boolean().default(false),
  href: z.string().startsWith("/"),
  id: z.string().min(1),
  pinned: z.boolean().default(false),
  title: z.string().min(1),
});

export const SidebarProjectsResponseSchema = z.object({
  data: z.array(SidebarProjectSchema),
  meta: z.object({ total: z.number().int().nonnegative() }),
});

export type SidebarConversation = z.infer<typeof SidebarConversationSchema>;
export type SidebarConversationStatus = z.infer<
  typeof SidebarConversationStatusSchema
>;
export type SidebarProject = z.infer<typeof SidebarProjectSchema>;
export type SidebarProjectsResponse = z.infer<
  typeof SidebarProjectsResponseSchema
>;
