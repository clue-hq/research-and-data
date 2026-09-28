import type { ResearchEvidence, ResearchItem, ResearchSection } from "./research-display";

/**
 * The Sources list for a page: one record per distinct source URL actually
 * cited by the page's sections or explicitly served as custom-field evidence.
 * Retiring a field removes its column while its authorized sources remain available.
 */
export function researchSources(sections: ResearchSection[], evidence: ResearchEvidence[]) {
  const claimIds = new Set(sections.flatMap((section) => [
    ...(section.intro ?? []).flatMap((sentence) => sentence.claimIds),
    ...section.items.flatMap((item) => [...item.body.flatMap((sentence) => sentence.claimIds), ...(item.sendLine?.claimIds ?? [])]),
  ]));
  for (const record of evidence) {
    if (claimIds.has(record.claimId)) for (const id of record.supportingClaimIds ?? []) claimIds.add(id);
  }
  const records = evidence.filter((record) => record.researchFieldKey || ((record.sourceUrl || record.sourceKind) && claimIds.has(record.claimId)));
  return [...new Map(records.map((record) => [record.sourceUrl ?? record.claimId, record])).values()];
}

export function researchCountLabel(sections: ResearchSection[]) {
  const count = sections.filter((section) => !section.restricted).reduce((n, section) => n + section.items.length, 0);
  return `${count} research insight${count === 1 ? "" : "s"}`;
}

export function isNewResearch(item: ResearchItem, evidence: Map<string, ResearchEvidence>, lastVisit: string | null) {
  if (!lastVisit || !Number.isFinite(Date.parse(lastVisit))) return false;
  return item.body.flatMap((sentence) => sentence.claimIds).some((id) => {
    const record = evidence.get(id);
    return record && Date.parse(`${record.verifiedAt}T00:00:00Z`) > Date.parse(lastVisit);
  });
}
