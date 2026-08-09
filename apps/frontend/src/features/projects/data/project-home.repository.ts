import {
  ProjectBootstrapResponseSchema,
  ProjectHomeResponseSchema,
  ProjectHomeSchema,
  type ProjectBootstrap,
  type ProjectHome,
} from "../model/project-workspace";
import { chatRequest, type ChatTransport } from "./chat-api";
import { FIXTURE_PROJECT_ID, FIXTURE_THREAD_ID } from "./chat.fixture";
import { projectHomeFixture } from "./project-workspace.fixture";

export interface CreateHomeProjectInput {
  brandId: string;
  message: string;
  idempotencyKey: string;
}

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
    async create({ brandId, message, idempotencyKey }) {
      return ProjectBootstrapResponseSchema.parse(
        await chatRequest(transport, "/projects", {
          method: "POST",
          idempotencyKey,
          body: {
            brand_id: brandId,
            message,
            context_refs: [],
            attachment_refs: [],
            agent_profile_id: null,
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
    async create({ brandId, message, idempotencyKey }) {
      const replay = accepted.get(idempotencyKey);
      if (replay) {
        return { ...replay, turn: { ...replay.turn, replayed: true } };
      }
      const now = new Date().toISOString();
      const href = `/projects/${FIXTURE_PROJECT_ID}?thread=${FIXTURE_THREAD_ID}`;
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
          title: message.trim(),
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
