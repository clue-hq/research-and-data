import { z } from "zod";

/**
 * The projects directory — one card per project, and the two pure functions the
 * screen sorts and searches with.
 *
 * The wire is the chat surface's snake_case `ProjectDirectoryItemWire`; the view
 * model is camelCase. The transform is the only place the two spellings meet, so
 * no component ever reads a backend field name.
 *
 * `activity` is *counted* by the backend, never guessed here: a card that says
 * "2 running" is reporting rows, not a client-side heuristic over a partial list.
 */

const ActivitySchema = z.object({
  chats: z.number().int(),
  running: z.number().int(),
  needsInput: z.number().int(),
});

export const DirectoryProjectSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  description: z.string().max(2000).default(""),
  href: z.string().startsWith("/projects/"),
  status: z.enum(["active", "archived"]),
  pinned: z.boolean(),
  brandId: z.string().min(1),
  productId: z.string().nullable(),
  createdAt: z.string().min(1),
  updatedAt: z.string().min(1),
  archivedAt: z.string().nullable(),
  activity: ActivitySchema,
});

export type DirectoryProject = z.infer<typeof DirectoryProjectSchema>;
export type ProjectActivity = z.infer<typeof ActivitySchema>;
export type DirectoryStatus = DirectoryProject["status"];

const ItemWire = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  description: z.string().default(""),
  href: z.string().min(1),
  status: z.enum(["active", "archived"]),
  pinned: z.boolean(),
  brand_id: z.string().min(1),
  product_id: z.string().nullable(),
  created_at: z.string().min(1),
  updated_at: z.string().min(1),
  archived_at: z.string().nullable(),
  activity: z.object({
    chats: z.number().int(),
    running: z.number().int(),
    needs_input: z.number().int(),
  }),
});

function fromWire(wire: z.infer<typeof ItemWire>): DirectoryProject {
  return DirectoryProjectSchema.parse({
    id: wire.id,
    title: wire.title,
    description: wire.description,
    href: wire.href,
    status: wire.status,
    pinned: wire.pinned,
    brandId: wire.brand_id,
    productId: wire.product_id,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
    archivedAt: wire.archived_at,
    activity: {
      chats: wire.activity.chats,
      running: wire.activity.running,
      needsInput: wire.activity.needs_input,
    },
  });
}

export const DirectoryProjectWireSchema = ItemWire.transform(fromWire);

/** One project envelope — what create, patch, and archive each return. */
export const DirectoryItemResponseSchema = z
  .object({ data: ItemWire })
  .transform((response) => fromWire(response.data));

/** One cursor page of the directory listing. */
export const DirectoryPageWireSchema = z
  .object({
    data: z.array(ItemWire),
    meta: z.object({ next_cursor: z.string().nullable() }),
  })
  .transform((page) => ({
    projects: page.data.map(fromWire),
    nextCursor: page.meta.next_cursor,
  }));

export type DirectoryPage = z.infer<typeof DirectoryPageWireSchema>;

export function projectHomeHref(id: string) {
  return `/projects/${encodeURIComponent(id)}`;
}

export type DirectorySort = "updated" | "created" | "name";

/**
 * Pinned projects first, then the chosen comparator — the directory's one
 * ordering rule, so the grid and any other consumer can never disagree.
 */
export function sortDirectory(
  projects: readonly DirectoryProject[],
  sort: DirectorySort,
): DirectoryProject[] {
  return [...projects].sort(
    (a, b) =>
      Number(b.pinned) - Number(a.pinned) ||
      (sort === "name"
        ? a.title.localeCompare(b.title)
        : sort === "created"
          ? b.createdAt.localeCompare(a.createdAt)
          : b.updatedAt.localeCompare(a.updatedAt)),
  );
}

/** The search box: a case-insensitive substring over the title and description. */
export function filterDirectory(
  projects: readonly DirectoryProject[],
  query: string,
): DirectoryProject[] {
  const needle = query.toLowerCase();
  return projects.filter((project) =>
    `${project.title} ${project.description}`.toLowerCase().includes(needle),
  );
}

/**
 * The card's date stamp. UTC-pinned so a server render and a browser render of
 * the same timestamp produce the same string.
 */
export function formatProjectDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}
