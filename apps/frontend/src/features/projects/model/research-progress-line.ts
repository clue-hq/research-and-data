import type { ResearchProgress } from "./research-progress";

/** "7 research agents running, 3 accounts queued" — the mockup's second line. */
export function researchProgressHeadline(card: ResearchProgress): string {
  const agents = `${card.running} research ${card.running === 1 ? "agent" : "agents"} running`;
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
  if (card.pill === "completed") {
    return `Research complete for ${card.finished} ${card.finished === 1 ? "account" : "accounts"}`;
  }
  if (card.agents.length === 0) {
    return card.pill === "needs_attention" ? "Research needs attention" : "Research queued for an available agent";
  }
  const agent = card.agents[tick % card.agents.length];
  const subject = agent.subject === "person"
    ? `${agent.subject_name ?? "Committee member"} at ${agent.account_name}` : agent.account_name;
  switch (agent.stage) {
    case "researching": return `${subject}: researching and reviewing evidence`;
    case "compiling_findings": return `${subject}: compiling research findings`;
    case "storing_claims": return `${subject}: storing claims`;
    case "writing_narrative": return `${subject}: writing the research narrative`;
    case "completed": return `${subject}: completed`;
  }
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
