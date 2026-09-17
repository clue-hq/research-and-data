import { composerEntityImagePath } from "../model/project-workspace";
import { z } from "zod";
import {
  PreparedComposerContextSchema,
  type ChatContextRef,
  type PreparedComposerContext,
} from "../model/chat-context-handoff";
import { chatRequest, ClueChatApiError, type ChatTransport } from "./chat-api";

const PreparedComposerContextWireSchema = z.object({
  data: z.object({
    project_id: z.string().min(1),
    thread_id: z.string().min(1).nullable(),
    context_entities: z.array(z.object({
      object_type: z.enum(["account", "contact"]),
      object_id: z.string().min(1),
      label: z.string().min(1),
      secondary_label: z.string().min(1),
      image_url: z.string().nullable(),
      version: z.number().int().positive(),
      account_id: z.string().min(1).nullable().default(null),
      account_name: z.string().min(1).nullable().default(null),
    })).min(1).max(100),
  }),
}).transform(({ data }) =>
  PreparedComposerContextSchema.parse({
    projectId: data.project_id,
    threadId: data.thread_id,
    entities: data.context_entities.map((entity) => ({
      ...(entity.account_id ? { accountId: entity.account_id } : {}),
      ...(entity.account_name ? { accountName: entity.account_name } : {}),
      id: entity.object_id,
      imagePath: composerEntityImagePath(entity.image_url),
      label: entity.label,
      secondaryLabel: entity.secondary_label,
      type: entity.object_type,
      version: entity.version,
    })),
  }),
);

export interface ComposerContextRepository {
  prepare(input: {
    contextRefs: readonly ChatContextRef[];
    projectId: string;
    threadId?: string;
  }): Promise<PreparedComposerContext>;
}

export function createHttpComposerContextRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ComposerContextRepository {
  return {
    async prepare({ contextRefs, projectId, threadId }) {
      return PreparedComposerContextWireSchema.parse(
        await chatRequest(
          transport,
          `/projects/${encodeURIComponent(projectId)}/composer-context/prepare`,
          {
            method: "POST",
            body: {
              thread_id: threadId ?? null,
              context_refs: contextRefs.map((reference) => ({
                object_type: reference.objectType,
                object_id: reference.objectId,
                version: reference.version,
              })),
            },
          },
        ),
      );
    },
  };
}

export const unavailableComposerContextRepository: ComposerContextRepository = {
  async prepare() {
    throw new ClueChatApiError(
      "Chat context handoff is unavailable in fixture mode.",
      { code: "CAPABILITY_UNAVAILABLE", status: 409, requestId: null },
    );
  },
};
