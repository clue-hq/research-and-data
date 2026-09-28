import { documentKindLabel, type ProjectDocument } from "./project-documents";
import type {
  GalleryCollateralType,
  ProjectArtifact,
  ProjectEntity,
} from "./project-workspace";

export type ComposerCategory = "files" | "microsites" | "accounts";

export const COMPOSER_CATEGORIES: readonly {
  key: ComposerCategory;
  label: string;
  empty: string;
}[] = [
  { key: "files", label: "Files", empty: "No files in the Gallery yet" },
  { key: "microsites", label: "Microsites", empty: "No microsites yet" },
  { key: "accounts", label: "Accounts", empty: "No accounts yet" },
];

export const MENTION_QUERY_MAX = 60;

const COLLATERAL_LABELS: Record<GalleryCollateralType, string> = {
  "account-list": "Account list",
  "direct-mail": "Direct mail",
  "linkedin-ad": "LinkedIn ad",
  "meta-ad": "Meta ad",
  microsite: "Microsite",
  presentation: "Presentation",
  report: "Report",
};

export function entityCategory(entity: ProjectEntity): ComposerCategory {
  return entity.category ?? "accounts";
}

function byLabel(left: ProjectEntity, right: ProjectEntity) {
  return left.label.localeCompare(right.label);
}

/**
 * The picker's whole catalog, built from the same feeds the Gallery renders. The Gallery is
 * the file system: nothing appears here that is not a Gallery card, and no card carries a
 * path or an id into a label.
 */
export function buildComposerCatalog({
  documents,
  artifacts,
  entities,
}: {
  documents: readonly ProjectDocument[];
  artifacts: readonly ProjectArtifact[];
  entities: readonly ProjectEntity[];
}): ProjectEntity[] {
  const files: ProjectEntity[] = documents.map((document) => ({
    category: "files",
    icon: "file-text",
    id: document.id,
    label: document.title,
    secondaryLabel: documentKindLabel(document.kind),
    type: "project_document",
    version: document.version,
  }));
  const ads: ProjectEntity[] = [];
  const microsites: ProjectEntity[] = [];
  for (const artifact of artifacts) {
    if (!artifact.documentId || !artifact.version) continue;
    if (artifact.type === "website") {
      microsites.push({
        category: "microsites",
        icon: "web",
        id: artifact.documentId,
        label: artifact.title,
        secondaryLabel: "Microsite",
        type: "design_document",
        version: artifact.version,
      });
    } else if (artifact.type === "canvas") {
      ads.push({
        category: "files",
        icon: "image",
        id: artifact.documentId,
        label: artifact.title,
        secondaryLabel: artifact.collateralType
          ? COLLATERAL_LABELS[artifact.collateralType]
          : "Ad",
        type: "design_document",
        version: artifact.version,
      });
    }
  }
  return [
    ...files.sort(byLabel),
    ...ads.sort(byLabel),
    ...microsites.sort(byLabel),
    ...entities.map((entity) => ({ ...entity, category: "accounts" as const })),
  ];
}

/** Per category, how many rows the user can open to. Accounts counts accounts, not their contacts. */
export function composerCategoryCounts(
  catalog: readonly ProjectEntity[],
): Record<ComposerCategory, number> {
  const counts = { files: 0, microsites: 0, accounts: 0 };
  for (const entity of catalog) {
    if (entity.type === "contact") continue;
    counts[entityCategory(entity)] += 1;
  }
  return counts;
}

/** How many discovered contacts each account carries, by account id. */
export function contactCountsByAccount(
  catalog: readonly ProjectEntity[],
): ReadonlyMap<string, number> {
  const counts = new Map<string, number>();
  for (const entity of catalog) {
    if (entity.type !== "contact" || !entity.accountId) continue;
    counts.set(entity.accountId, (counts.get(entity.accountId) ?? 0) + 1);
  }
  return counts;
}

/**
 * The Accounts list as a tree: every account in catalog order, each followed by its contacts
 * only while it is expanded. A contact whose account is not in the catalog trails the list
 * flat, so it stays reachable rather than vanishing.
 */
export function accountTreeRows(
  catalog: readonly ProjectEntity[],
  expandedAccountIds: ReadonlySet<string>,
): ProjectEntity[] {
  const accounts = catalog.filter((entity) => entity.type === "account");
  const known = new Set(accounts.map((account) => account.id));
  const contactsByAccount = new Map<string, ProjectEntity[]>();
  const orphans: ProjectEntity[] = [];
  for (const entity of catalog) {
    if (entity.type !== "contact") continue;
    if (entity.accountId && known.has(entity.accountId)) {
      const siblings = contactsByAccount.get(entity.accountId) ?? [];
      siblings.push(entity);
      contactsByAccount.set(entity.accountId, siblings);
    } else {
      orphans.push(entity);
    }
  }
  const rows = accounts.flatMap((account) =>
    expandedAccountIds.has(account.id)
      ? [account, ...(contactsByAccount.get(account.id) ?? [])]
      : [account],
  );
  return [...rows, ...orphans];
}

/** Typing searches every category at once; the catalog's category order is kept. */
export function searchComposerCatalog(
  catalog: readonly ProjectEntity[],
  query: string,
): ProjectEntity[] {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return [];
  return catalog.filter((entity) =>
    `${entity.label} ${entity.secondaryLabel} ${entity.accountName ?? ""}`
      .toLocaleLowerCase()
      .includes(needle),
  );
}

/**
 * The text after an `@` that starts a word, up to the caret. Spaces are allowed so a title
 * like "Project plan" can be typed; a second `@` starts a new query; an over-long query is no
 * query (the user is writing prose).
 */
export function detectMentionQuery(beforeText: string): string | null {
  const match = beforeText.match(/(?:^|\s)@([^@\n]*)$/);
  if (!match) return null;
  const query = match[1] ?? "";
  return query.length > MENTION_QUERY_MAX ? null : query;
}

/** Prose recovers by itself: a query that matches nothing and just gained a space closes the picker. */
export function shouldAutoCloseMention(query: string, matchCount: number): boolean {
  return matchCount === 0 && query.endsWith(" ");
}
