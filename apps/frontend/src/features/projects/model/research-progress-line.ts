import type { ResearchProgress } from "./research-progress";

/** "7 account research agents running, 3 accounts queued" — the mockup's second line. */
export function researchProgressHeadline(card: ResearchProgress): string {
  const agents = `${card.running} account research ${card.running === 1 ? "agent" : "agents"} running`;
  const queued = `${card.queued} ${card.queued === 1 ? "account" : "accounts"} queued`;
  return `${agents}, ${queued}`;
}

/**
 * The bottom line of the card (spec §5): one sentence at a time, round-robin over the running
 * agents by `tick`, worded by stage. A person job reads as the member line for its account.
 */
export function researchProgressLine(card: ResearchProgress, tick: number): string {
  if (card.pill === "needs_attention" && card.attention.length) {
    const item = card.attention[tick % card.attention.length];
    return `${item.account_name}: ${item.reason}`;
  }
  if (card.pill === "completed" || card.agents.length === 0) {
    return `Research complete for ${card.finished} ${card.finished === 1 ? "account" : "accounts"}`;
  }
  const agent = card.agents[tick % card.agents.length];
  if (agent.subject === "person" || agent.stage === "member_research") {
    return `Diving deeper into each committee member of ${agent.account_name}`;
  }
  switch (agent.stage) {
    case "synthesis":
      return `Synthesising our findings for ${agent.account_name}`;
    case "committee":
      return `Finding the buying committee for ${agent.account_name}`;
    default:
      return `${agent.account_name} agent doing deep research`;
  }
}
