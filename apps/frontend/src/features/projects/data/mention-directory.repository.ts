import { z } from "zod";
import {
  composerEntityImagePath,
  type ProjectEntity,
} from "../model/project-workspace";
import { chatUrl, refusalOf, type ChatTransport } from "./chat-api";

/**
 * The @ tagger's directory: every account and committee contact in the
 * workspace, names and ids only (2026-10-05).
 *
 * Before this the tagger offered only the 50 newest accounts, filtered in the
 * browser, so an older account could not be tagged whatever was typed. The
 * directory is loaded once, kept for the session, and re-checked with
 * `If-None-Match`: an unchanged directory is a bodiless 304. When the
 * workspace is too large to send whole, `complete` is false and the composer
 * also asks {@link MentionDirectoryRepository.search} as the user types.
 */
export interface MentionDirectory {
  entities: ProjectEntity[];
  complete: boolean;
  etag: string | null;
}

export type MentionDirectoryLoad =
  | { status: "loaded"; directory: MentionDirectory }
  | { status: "unchanged" }
  // No backend to ask (fixture mode): the composer keeps its own entities.
  | { status: "unavailable" };

export interface MentionDirectoryRepository {
  load(input: {
    projectId: string | null;
    etag: string | null;
    signal?: AbortSignal;
  }): Promise<MentionDirectoryLoad>;
  search(input: { query: string; signal?: AbortSignal }): Promise<ProjectEntity[]>;
}

const EntityWireSchema = z.object({
  object_type: z.enum(["account", "contact"]),
  object_id: z.string().min(1),
  label: z.string().min(1),
  secondary_label: z.string().min(1),
  image_url: z.string().nullable(),
  account_id: z.string().min(1).nullable().default(null),
  account_name: z.string().min(1).nullable().default(null),
});

function entityOf(entity: z.infer<typeof EntityWireSchema>): ProjectEntity {
  const imagePath = composerEntityImagePath(entity.image_url);
  return {
    ...(entity.account_id ? { accountId: entity.account_id } : {}),
    ...(entity.account_name ? { accountName: entity.account_name } : {}),
    id: entity.object_id,
    ...(imagePath ? { imagePath } : {}),
    label: entity.label,
    secondaryLabel: entity.secondary_label,
    type: entity.object_type,
  };
}

const DirectoryWireSchema = z.object({
  data: z.object({
    entities: z.array(EntityWireSchema),
    complete: z.boolean(),
  }),
});

const SearchWireSchema = z.object({
  data: z.object({ entities: z.array(EntityWireSchema) }),
});

export function createHttpMentionDirectoryRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
  fetchImpl: typeof fetch = (input, init) => fetch(input, init),
): MentionDirectoryRepository {
  return {
    async load({ projectId, etag, signal }) {
      const headers = new Headers({ Accept: "application/json" });
      if (etag) headers.set("If-None-Match", etag);
      const response = await fetchImpl(
        chatUrl(transport, "/mention-directory", { project_id: projectId ?? undefined }),
        // The browser's own HTTP cache stays out of it: the ETag is ours to send.
        { headers, cache: "no-store", signal },
      );
      if (response.status === 304) return { status: "unchanged" };
      if (!response.ok) throw await refusalOf(response);
      const { data } = DirectoryWireSchema.parse(await response.json());
      return {
        status: "loaded",
        directory: {
          entities: data.entities.map(entityOf),
          complete: data.complete,
          etag: response.headers.get("ETag"),
        },
      };
    },
    async search({ query, signal }) {
      const response = await fetchImpl(
        chatUrl(transport, "/mention-directory/search", { q: query }),
        { headers: { Accept: "application/json" }, cache: "no-store", signal },
      );
      if (!response.ok) throw await refusalOf(response);
      return SearchWireSchema.parse(await response.json()).data.entities.map(entityOf);
    },
  };
}

export const unavailableMentionDirectoryRepository: MentionDirectoryRepository = {
  async load() {
    return { status: "unavailable" };
  },
  async search() {
    return [];
  },
};
