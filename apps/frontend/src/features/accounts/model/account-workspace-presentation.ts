import type { AccountArtifact, AccountWorkspace } from "./account-workspace";

export const artifactTypeLabels: Record<AccountArtifact["type"], string> = {
  ad: "Ad",
  web: "Landing page",
  document: "Document",
  presentation: "Presentation",
  email: "Email",
};

export const artifactTypeOptions = [
  { value: "all", label: "All types" },
  { value: "ad", label: "Ads" },
  { value: "web", label: "Landing pages" },
  { value: "document", label: "Documents" },
  { value: "presentation", label: "Presentations" },
  { value: "email", label: "Emails" },
];

export function formatAccountDate(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  }).format(new Date(value));
}

/**
 * Which served summary strings the Insights header strip shows.
 *
 * The strings themselves are the backend's ("{n} insights", "{m} people" —
 * contract v1); nothing here rewrites one. The research date is served in the
 * same list and is rendered under Sources instead of in the strip, so only the
 * choice of slot lives here.
 */
export function insightHeaderSummary(summary: string[]) {
  return summary.filter((item) => !/^researched\b/i.test(item));
}

export function accountArtifacts(artifacts: AccountArtifact[], accountId: string) {
  // Legacy responses are already scoped by their account-workspace endpoint.
  // Explicit associations must match: never borrow another account's creatives.
  return artifacts.filter((artifact) => !artifact.accountId || artifact.accountId === accountId);
}

export function filterAccountArtifacts(
  artifacts: AccountArtifact[],
  { search = "", type = "all", sort = "recent" } = {},
) {
  const query = search.trim().toLocaleLowerCase();
  return artifacts.filter((artifact) =>
    (type === "all" || artifact.type === type) &&
    (!query || [artifact.title, artifact.projectName, artifactTypeLabels[artifact.type]]
      .some((value) => value?.toLocaleLowerCase().includes(query))),
  ).sort((a, b) => {
    if (sort === "name") return a.title.localeCompare(b.title);
    if (sort === "type") return artifactTypeLabels[a.type].localeCompare(artifactTypeLabels[b.type]) || a.title.localeCompare(b.title);
    // Keep legacy records in supplied order when no sortable timestamp exists.
    if (!a.updatedAt) return b.updatedAt ? 1 : 0;
    if (!b.updatedAt) return -1;
    return Date.parse(b.updatedAt) - Date.parse(a.updatedAt);
  });
}

type Activity = AccountWorkspace["activity"][number];

/**
 * The actor and phrasing an activity row renders.
 *
 * The actor is the served `actor` discriminated union and nothing else: an
 * event with no actor is unattributed (contract v1), never guessed from the
 * wording of its text.
 */
export function activityPresentation(item: Activity) {
  const actorType = item.actor?.type;
  const actorName = item.actor?.type === "person" ? item.actor.name : actorType === "clue" ? "Clue" : undefined;
  return {
    actorType,
    actorName,
    action: item.action ?? item.text,
  };
}

export function filterAccountActivity(items: Activity[], actor: string) {
  const filtered = items.filter((item) => actor === "all" || activityPresentation(item).actorType === actor);
  // Partial/legacy dates cannot establish a different chronology reliably.
  // Keep the endpoint's supplied order unless every event has a timestamp.
  if (!filtered.every((item) => item.occurredAt)) return filtered;
  return filtered.sort((a, b) => Date.parse(b.occurredAt!) - Date.parse(a.occurredAt!));
}
