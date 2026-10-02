import type { GateDecision } from "../model/chat-parts";

/**
 * The small amount of state the fixture adapters share.
 *
 * The fixture repositories stand in for one backend, so they must agree with
 * each other the way that backend does: answering a gate through the *turn*
 * endpoint is what closes the gate the *gates* read returns, and it is what
 * makes the next turn a launch narration rather than another draft. Without a
 * shared record each adapter would tell a different story, and the fixture
 * would stop being a faithful rehearsal of the HTTP path.
 *
 * It holds nothing a real deployment would: no identity, no authority, no
 * durable claim — only which gate this session answered and which script a turn
 * is playing.
 */
export interface FixtureChatState {
  /** gateId → the decision this session recorded, and the turn that made it. */
  gateAnswers: Map<
    string,
    {
      turnId: string;
      decision: GateDecision;
      revisionRequest?: string;
      selectedProductId?: string;
      selectedProductIds?: readonly string[];
    }
  >;
  /** turnId → which scripted stream that turn plays. */
  scripts: Map<string, "turn" | "launch">;
}

export function createFixtureChatState(): FixtureChatState {
  return { gateAnswers: new Map(), scripts: new Map() };
}
