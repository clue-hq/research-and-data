import type { ResearchEvidence, ResearchItem, ResearchSection } from "./research-display";

export function researchSources(sections: ResearchSection[], evidence: ResearchEvidence[], includeRegister = false) {
  const claimIds = new Set(sections.flatMap((section) => [
    ...(section.intro ?? []).flatMap((sentence) => sentence.claimIds),
    ...section.items.flatMap((item) => [...item.body.flatMap((sentence) => sentence.claimIds), ...(item.sendLine?.claimIds ?? [])]),
  ]));
  const records = evidence.filter((record) => record.sourceUrl && (includeRegister ? record.claimId.startsWith("register-") || claimIds.has(record.claimId) : claimIds.has(record.claimId)));
  return [...new Map(records.map((record) => [record.sourceUrl!, record])).values()];
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

export function formatTenure(start: string, asOf: string) {
  const from = new Date(`${start}T00:00:00Z`);
  const to = new Date(`${asOf}T00:00:00Z`);
  const months = Math.max(0, (to.getUTCFullYear() - from.getUTCFullYear()) * 12 + to.getUTCMonth() - from.getUTCMonth() - (to.getUTCDate() < from.getUTCDate() ? 1 : 0));
  const parts = [Math.floor(months / 12) ? `${Math.floor(months / 12)} year${months >= 24 ? "s" : ""}` : "", months % 12 ? `${months % 12} month${months % 12 === 1 ? "" : "s"}` : ""].filter(Boolean);
  return `${from.toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" })} (${parts.join(" ") || "less than a month"})`;
}
