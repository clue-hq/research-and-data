import { z } from "zod";

export const SidebarConversationStatusSchema = z.enum([
  "idle",
  "running",
  "review",
  "approval",
  "needs-input",
]);

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
