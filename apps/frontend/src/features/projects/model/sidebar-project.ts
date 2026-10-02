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
  pinned: z.boolean().default(false),
  status: SidebarConversationStatusSchema.default("idle"),
  title: z.string().min(1),
  updatedAt: z.string().min(1),
});

export const SidebarProjectSchema = z.object({
  conversations: z.array(SidebarConversationSchema),
  expanded: z.boolean().default(false),
  href: z.string().startsWith("/"),
  id: z.string().min(1),
  pinned: z.boolean().default(false),
  title: z.string().min(1),
  /**
   * Optional because the sidebar itself never shows it: it is here so the one
   * project record can also seed a directory card without a second read.
   */
  updatedAt: z.string().min(1).optional(),
});

export const SidebarProjectsResponseSchema = z.object({
  data: z.array(SidebarProjectSchema),
  meta: z.object({ nextCursor: z.string().min(1).nullable() }),
});

const SidebarProjectsWireSchema = z.object({
  data: z.array(z.object({
    id: z.string().min(1),
    title: z.string().min(1),
    href: z.string().startsWith("/projects/"),
    // Defaulted rather than required so a deployment that predates the
    // directory work still serves a readable sidebar.
    pinned: z.boolean().default(false),
    updated_at: z.string().min(1).optional(),
    conversations: z.array(z.object({
      id: z.string().min(1),
      title: z.string().min(1).nullable(),
      href: z.string().startsWith("/projects/"),
      status: SidebarConversationStatusSchema,
      pinned: z.boolean(),
      updated_at: z.string().min(1),
    })),
  })),
  meta: z.object({ next_cursor: z.string().min(1).nullable() }),
});

export const SidebarProjectsWireResponseSchema = SidebarProjectsWireSchema.transform(
  ({ data, meta }) =>
    SidebarProjectsResponseSchema.parse({
      data: data.map((project) => ({
        conversations: project.conversations.map((conversation) => ({
          href: conversation.href,
          id: conversation.id,
          pinned: conversation.pinned,
          status: conversation.status,
          title: conversation.title ?? "New chat",
          updatedAt: conversation.updated_at,
        })),
        expanded: false,
        href: project.href,
        id: project.id,
        pinned: project.pinned,
        title: project.title,
        updatedAt: project.updated_at,
      })),
      meta: { nextCursor: meta.next_cursor },
    }),
);

export type SidebarConversation = z.infer<typeof SidebarConversationSchema>;
export type SidebarConversationStatus = z.infer<
  typeof SidebarConversationStatusSchema
>;
export type SidebarProject = z.infer<typeof SidebarProjectSchema>;
export type SidebarProjectsResponse = z.infer<
  typeof SidebarProjectsResponseSchema
>;
