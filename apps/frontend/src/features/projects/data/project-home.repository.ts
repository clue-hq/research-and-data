import {
  ProjectBootstrapRequestSchema,
  ProjectBootstrapResponseSchema,
  ProjectHomeResponseSchema,
  ProjectHomeSchema,
  type ProjectBootstrap,
  type ProjectBootstrapRequestInput,
  type ProjectHome,
} from "../model/project-workspace";
import { chatRequest, type ChatTransport } from "./chat-api";
import { FIXTURE_PROJECT_ID, FIXTURE_THREAD_ID } from "./chat.fixture";
import { projectHomeFixture } from "./project-workspace.fixture";

export type CreateHomeProjectInput = ProjectBootstrapRequestInput & {
  idempotencyKey: string;
};

export interface ProjectHomeRepository {
  get(): Promise<ProjectHome>;
  create(input: CreateHomeProjectInput): Promise<ProjectBootstrap>;
}

export function createHttpProjectHomeRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ProjectHomeRepository {
  return {
    async get() {
      return ProjectHomeResponseSchema.parse(
        await chatRequest(transport, "/home"),
      );
    },
    async create({ idempotencyKey, ...input }) {
      const request = ProjectBootstrapRequestSchema.parse(input);
      return ProjectBootstrapResponseSchema.parse(
        await chatRequest(transport, "/projects", {
          method: "POST",
          idempotencyKey,
          body: {
            brand_id: request.brandId,
            message: request.message,
            context_refs: request.contextRefs.map((reference) => ({
              object_type: reference.objectType,
              object_id: reference.objectId,
              version: reference.version,
            })),
            attachment_refs: request.attachmentRefs.map((reference) => ({
              upload_id: reference.uploadId,
              artifact_key: reference.artifactKey,
              sha256: reference.sha256,
              media_type: reference.mediaType,
              byte_count: reference.byteCount,
              filename: reference.filename,
            })),
            agent_profile_id: request.agentProfileId,
          },
        }),
      );
    },
  };
}

export function createFixtureProjectHomeRepository(): ProjectHomeRepository {
  const accepted = new Map<string, ProjectBootstrap>();
  return {
    async get() {
      return ProjectHomeSchema.parse(projectHomeFixture);
    },
    async create({ idempotencyKey, ...input }) {
      const { brandId } = ProjectBootstrapRequestSchema.parse(input);
      const replay = accepted.get(idempotencyKey);
      if (replay) {
        return { ...replay, turn: { ...replay.turn, replayed: true } };
      }
      const now = new Date().toISOString();
      const href = `/projects/${FIXTURE_PROJECT_ID}/chats/${FIXTURE_THREAD_ID}`;
      const created: ProjectBootstrap = {
        href,
        project: {
          id: FIXTURE_PROJECT_ID,
          title: "Untitled project",
          brandId,
          href: `/projects/${FIXTURE_PROJECT_ID}`,
          createdAt: now,
        },
        thread: {
          id: FIXTURE_THREAD_ID,
          // Born untitled; the conversation namer titles it after the first completed turn.
          title: null,
          href,
          status: "running",
          pinned: false,
          projectId: FIXTURE_PROJECT_ID,
          createdAt: now,
          updatedAt: now,
        },
        turn: {
          turnId: "fixture-home-turn",
          threadId: FIXTURE_THREAD_ID,
          requestedAt: now,
          replayed: false,
        },
      };
      accepted.set(idempotencyKey, created);
      return created;
    },
  };
}
