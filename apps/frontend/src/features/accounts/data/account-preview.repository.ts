import { AccountDetailResponseSchema } from "../model/account-detail";
import { withResearchContext, type ResearchContextQuery } from "../model/research-context";

export async function fetchAccountPreview(accountId: string, context: ResearchContextQuery, signal: AbortSignal) {
  const response = await fetch(withResearchContext(`/api/accounts/${encodeURIComponent(accountId)}`, context), { signal });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("Unable to load account details");
  return AccountDetailResponseSchema.parse(await response.json()).data;
}
