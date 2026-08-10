import {
  ChatInspectorContextResponseSchema,
  ChatInspectorCapabilitySchema,
  ChatInspectorPlanResponseSchema,
  ChatInspectorRoundsResponseSchema,
  ChatInspectorToolsResponseSchema,
  type ChatInspectorCapability,
  type ChatInspectorContext,
  type ChatInspectorPlanView,
  type ChatInspectorRound,
  type ChatInspectorToolsView,
} from "../model/chat-inspector";
import { ClueChatApiError, chatRequest, type ChatTransport } from "./chat-api";
import {
  fixtureInspectorContext,
  fixtureInspectorPlan,
  fixtureInspectorRounds,
  fixtureInspectorTools,
} from "./chat.fixture";

/**
 * The dev-lens turn-context inspector.
 *
 * **Capability is discovered, never configured client-side.** The four routes
 * exist only in a development deployment: the backend refuses to construct with
 * the flag set in production, and with it unset never registers them. So this
 * repository *asks* — and a 404 on the probe means "this deployment has no
 * inspector", which is the correct and only answer a client can give. A second
 * environment variable on this side could disagree with the server's; asking
 * cannot.
 *
 * Every read returns the same `{ available, … }` shape as the gate read, for
 * the same reason: an absent surface must be reported, not fabricated.
 */
export interface ChatInspectorProbe {
  available: boolean;
  capability: ChatInspectorCapability | null;
  reason: string | null;
}

export interface ChatInspectorRepository {
  probe(input: { projectId: string; threadId: string }): Promise<ChatInspectorProbe>;
  context(input: TurnScope): Promise<ChatInspectorContext | null>;
  rounds(input: TurnScope): Promise<readonly ChatInspectorRound[]>;
  plan(input: TurnScope): Promise<ChatInspectorPlanView>;
  tools(input: TurnScope): Promise<ChatInspectorToolsView>;
}

export interface TurnScope {
  projectId: string;
  threadId: string;
  turnId: string;
}

const UNSERVED =
  "this deployment does not serve the turn-context inspector (it is a " +
  "development lens and is never registered in production)";

function turnPath({ projectId, threadId, turnId }: TurnScope, tab: string): string {
  return (
    `/projects/${encodeURIComponent(projectId)}` +
    `/threads/${encodeURIComponent(threadId)}` +
    `/turns/${encodeURIComponent(turnId)}/inspector/${tab}`
  );
}

export function createHttpChatInspectorRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ChatInspectorRepository {
  return {
    async probe({ projectId, threadId }) {
      try {
        const capability = ChatInspectorCapabilitySchema.parse(
          await chatRequest(
            transport,
            `/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(
              threadId,
            )}/inspector`,
          ),
        );
        return { available: capability.enabled, capability, reason: null };
      } catch (error) {
        // A 404 here is the route being absent (the flag is off) or the thread
        // being invisible. Either way there is no inspector to offer, and the
        // affordance is simply not rendered.
        if (error instanceof ClueChatApiError && error.status === 404) {
          return { available: false, capability: null, reason: UNSERVED };
        }
        throw error;
      }
    },
    async context(scope) {
      return ChatInspectorContextResponseSchema.parse(
        await chatRequest(transport, turnPath(scope, "context")),
      );
    },
    async rounds(scope) {
      return ChatInspectorRoundsResponseSchema.parse(
        await chatRequest(transport, turnPath(scope, "rounds")),
      );
    },
    async plan(scope) {
      return ChatInspectorPlanResponseSchema.parse(
        await chatRequest(transport, turnPath(scope, "plan")),
      );
    },
    async tools(scope) {
      return ChatInspectorToolsResponseSchema.parse(
        await chatRequest(transport, turnPath(scope, "tools")),
      );
    },
  };
}

/**
 * The fixture adapter.
 *
 * It reports the inspector as **available**, because the fixture world exists so
 * the drawer can be built and tested without a backend, and its payloads run
 * through the same schemas the HTTP adapter parses — which is the only thing
 * that makes a fixture worth having.
 */
export function createFixtureChatInspectorRepository(): ChatInspectorRepository {
  return {
    async probe() {
      return {
        available: true,
        capability: ChatInspectorCapabilitySchema.parse({
          data: {
            enabled: true,
            tabs: ["context", "rounds", "plan", "tools"],
            budget_bytes: 512_000,
            bodies_available: true,
          },
        }),
        reason: null,
      };
    },
    async context({ turnId }) {
      return ChatInspectorContextResponseSchema.parse(fixtureInspectorContext(turnId));
    },
    async rounds() {
      return ChatInspectorRoundsResponseSchema.parse(fixtureInspectorRounds());
    },
    async plan({ turnId }) {
      return ChatInspectorPlanResponseSchema.parse(fixtureInspectorPlan(turnId));
    },
    async tools({ turnId }) {
      return ChatInspectorToolsResponseSchema.parse(fixtureInspectorTools(turnId));
    },
  };
}
