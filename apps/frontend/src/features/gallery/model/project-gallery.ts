import type {
  GalleryCollateralType,
  GallerySizeCategory,
  ProjectArtifact,
} from "@/features/projects/model/project-workspace";

import { documentEditedLabel, type ProjectDocument } from "@/features/projects/model/project-documents";

export type GalleryType = GalleryCollateralType | "documents";

export type GalleryLayout = "grid" | "list";
export type GalleryGroupBy = "none" | "account" | "type" | "project";
export type GalleryDateRange = "all" | "today" | "last-7-days" | "last-30-days";
export type GallerySort =
  | "last-viewed"
  | "edited-desc"
  | "edited-asc"
  | "name-asc"
  | "name-desc"
  | "account-asc"
  | "type-asc"
  | "project-asc";
export type GalleryMenu = "sort" | "group" | "filter" | null;

export interface GalleryFilters {
  accountIds: string[];
  collateralTypes: GalleryType[];
  dateRange: GalleryDateRange;
  projectIds?: string[];
  sizeCategories: GallerySizeCategory[];
}

export interface GalleryAccount {
  id: string;
  logoPath?: string;
  name: string;
}

export interface GalleryArtifact {
  /** Absent for a real, unattributed artifact — the card shows no account
   * badge rather than a fabricated one (ruling 2's no-invented-imagery,
   * extended to account attribution). */
  account?: GalleryAccount;
  /** G-H: absent when the document records no channel — "we are not
   * necessarily always making ads", so a card that cannot prove its channel
   * claims none (the same honest-absence rule `account` follows above). */
  collateralType?: GalleryType;
  document?: ProjectDocument;
  /** Empty when there is no collateral type to name. */
  collateralTypeLabel: string;
  createdAt: string;
  editedLabel: string;
  id: string;
  /** Absent for a real design document — it has no thumbnail (ruling 2). */
  imagePath?: string;
  lastViewedAt: string;
  /** Absent for a leg-derived document — no generation run produced it. */
  originRunId?: string;
  originThreadId?: string;
  /** The owning project — set by the library, absent in a project gallery. */
  project?: { id: string; title: string };
  /** G-H: absent when the document records no page size — the card shows no
   * size rather than a measurement nobody took. */
  size?: {
    category: GallerySizeCategory;
    height: number;
    label: string;
    width: number;
  };
  source?: ProjectArtifact;
  title: string;
  updatedAt: string;
}

export interface GalleryGroup {
  account?: GalleryAccount;
  artifacts: GalleryArtifact[];
  id: string;
  label: string;
}

export const DEFAULT_GALLERY_FILTERS: GalleryFilters = {
  accountIds: [],
  collateralTypes: [],
  dateRange: "all",
  sizeCategories: [],
};

export const COLLATERAL_TYPE_LABELS: Record<GalleryType, string> = {
  documents: "Documents",
  "account-list": "Account list",
  "direct-mail": "Direct mail",
  "linkedin-ad": "LinkedIn ad",
  "meta-ad": "Meta ad",
  microsite: "Microsite",
  presentation: "Presentation",
  report: "Report",
};

export const SIZE_CATEGORY_LABELS: Record<GallerySizeCategory, string> = {
  landscape: "Landscape",
  portrait: "Portrait",
  responsive: "Responsive",
  square: "Square",
};

function defaultCollateralType(
  artifact: ProjectArtifact,
): GalleryCollateralType | undefined {
  if (artifact.type === "website") return "microsite";
  if (artifact.type === "table") return "account-list";
  if (artifact.type === "presentation") return "presentation";
  // G-H: a canvas artifact used to default to "linkedin-ad", which stated a
  // channel nobody recorded. The feed now carries the document's own type when
  // it has one; when it does not, the card says nothing.
  return undefined;
}

function defaultAccount(artifact: ProjectArtifact): GalleryAccount | undefined {
  const logo = artifact.accountLogoPath;
  if (artifact.accountId && artifact.accountName) {
    return { id: artifact.accountId, logoPath: logo, name: artifact.accountName };
  }
  if (logo?.includes("anthropic")) {
    return { id: "anthropic", logoPath: logo, name: "Anthropic" };
  }
  if (logo?.includes("cursor")) {
    return { id: "cursor", logoPath: logo, name: "Cursor" };
  }
  if (logo) {
    return { id: "openai", logoPath: logo, name: "OpenAI" };
  }
  // No account hints at all — a real, unattributed artifact. Honest absence:
  // fabricating the fixture "OpenAI" here would paint fake attribution onto
  // real documents (the leg-derived feed's cards carry no account data).
  return undefined;
}

function defaultSize(artifact: ProjectArtifact): GalleryArtifact["size"] {
  if (artifact.type === "website" || artifact.type === "table") {
    return {
      category: "responsive",
      height: 900,
      label: "Responsive",
      width: 1440,
    };
  }
  // G-H: a canvas artifact used to claim 1080x1080 whatever its page really
  // measured. The feed carries the document's real pixels; without them the
  // card states no size at all.
  return undefined;
}

export function normalizeGalleryArtifact(artifact: ProjectArtifact): GalleryArtifact & { source: ProjectArtifact } {
  const collateralType = artifact.collateralType ?? defaultCollateralType(artifact);
  const updatedAt = artifact.updatedAt ?? "2026-08-16T12:00:00.000Z";
  // The library hands its own `LibraryArtifact` rows through this same
  // normalizer, so the owning project is read structurally: a project gallery's
  // artifacts carry neither field and normalize to no project at all.
  const library = artifact as ProjectArtifact & { projectId?: string; projectTitle?: string };
  return {
    account: defaultAccount(artifact),
    collateralType,
    collateralTypeLabel: collateralType ? COLLATERAL_TYPE_LABELS[collateralType] : "",
    createdAt: artifact.createdAt ?? updatedAt,
    editedLabel: artifact.editedLabel,
    id: artifact.id,
    imagePath: artifact.imagePath,
    lastViewedAt: artifact.lastViewedAt ?? updatedAt,
    originRunId: artifact.originRunId,
    originThreadId: artifact.originThreadId,
    project: library.projectId
      ? { id: library.projectId, title: library.projectTitle ?? "Untitled project" }
      : undefined,
    size: artifact.size ?? defaultSize(artifact),
    source: artifact,
    title: artifact.title,
    updatedAt,
  };
}

/** Documents keep their own model: they have no design canvas, account, dimensions or thread. */
export function documentGalleryCards(documents: readonly ProjectDocument[], now = new Date()): GalleryArtifact[] {
  return documents.map((document) => ({
    id: `document:${document.path}`, document,
    collateralType: "documents", collateralTypeLabel: "Documents",
    title: document.title, editedLabel: documentEditedLabel(document.updatedAt, now),
    updatedAt: document.updatedAt, createdAt: document.updatedAt, lastViewedAt: document.updatedAt,
  }));
}

export function galleryTypeOptions(artifacts: readonly GalleryArtifact[]): GalleryType[] {
  return (Object.keys(COLLATERAL_TYPE_LABELS) as GalleryType[])
    .filter((type) => type !== "documents" || artifacts.some((artifact) => !!artifact.document));
}

function withinDateRange(
  artifact: GalleryArtifact,
  dateRange: GalleryDateRange,
  now: Date,
) {
  if (dateRange === "all") return true;
  const updatedAt = new Date(artifact.updatedAt);
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  if (dateRange === "last-7-days") start.setDate(start.getDate() - 6);
  if (dateRange === "last-30-days") start.setDate(start.getDate() - 29);
  return updatedAt >= start && updatedAt <= now;
}

export function filterGalleryArtifacts({
  artifacts,
  filters,
  now = new Date(),
  query,
}: {
  artifacts: GalleryArtifact[];
  filters: GalleryFilters;
  now?: Date;
  query: string;
}) {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return artifacts.filter((artifact) => {
    if (filters.projectIds?.length && !filters.projectIds.includes(artifact.project?.id ?? "")) {
      return false;
    }
    if (
      filters.accountIds.length > 0 &&
      (!artifact.account || !filters.accountIds.includes(artifact.account.id))
    ) {
      return false;
    }
    if (
      filters.collateralTypes.length > 0 &&
      (artifact.collateralType === undefined ||
        !filters.collateralTypes.includes(artifact.collateralType))
    ) {
      return false;
    }
    if (
      filters.sizeCategories.length > 0 &&
      (artifact.size === undefined ||
        !filters.sizeCategories.includes(artifact.size.category))
    ) {
      return false;
    }
    if (!withinDateRange(artifact, filters.dateRange, now)) return false;
    if (!normalizedQuery) return true;
    return [
      artifact.title,
      artifact.account?.name ?? "",
      artifact.collateralTypeLabel,
      artifact.size?.label ?? "",
      artifact.project?.title ?? "",
    ].some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
  });
}

export function sortGalleryArtifacts(
  artifacts: GalleryArtifact[],
  sort: GallerySort,
) {
  return [...artifacts].sort((left, right) => {
    if (sort === "account-asc")
      return (left.account?.name ?? "").localeCompare(right.account?.name ?? "") || left.title.localeCompare(right.title);
    if (sort === "type-asc")
      return left.collateralTypeLabel.localeCompare(right.collateralTypeLabel) || left.title.localeCompare(right.title);
    if (sort === "project-asc")
      return (left.project?.title ?? "").localeCompare(right.project?.title ?? "") || left.title.localeCompare(right.title);
    if (sort === "name-asc") return left.title.localeCompare(right.title);
    if (sort === "name-desc") return right.title.localeCompare(left.title);
    if (sort === "edited-asc") return left.updatedAt.localeCompare(right.updatedAt);
    if (sort === "edited-desc") return right.updatedAt.localeCompare(left.updatedAt);
    return right.lastViewedAt.localeCompare(left.lastViewedAt);
  });
}

export function groupGalleryArtifacts(
  artifacts: GalleryArtifact[],
  groupBy: GalleryGroupBy,
): GalleryGroup[] {
  if (groupBy === "none") {
    return [{ artifacts, id: "all", label: "All artifacts" }];
  }

  const groups = new Map<string, GalleryGroup>();
  artifacts.forEach((artifact) => {
    // Unattributed artifacts share one honest group; its label stays empty
    // rather than inventing vocabulary (pending a founder ruling on wording).
    // G-H: a document that records no channel groups in the same honest
    // bucket an unattributed one does — empty label, no invented vocabulary.
    const id = groupBy === "project"
      ? (artifact.project?.id ?? "unassigned")
      : groupBy === "account"
        ? (artifact.account?.id ?? "unattributed")
        : (artifact.collateralType ?? "untyped");
    const label = groupBy === "project"
      ? (artifact.project?.title ?? "No project")
      : groupBy === "account"
        ? (artifact.account?.name ?? "")
        : artifact.collateralType === undefined
          ? ""
          : artifact.collateralType === "microsite"
            ? "Websites"
            : artifact.collateralType.includes("ad")
              ? "Ads"
              : COLLATERAL_TYPE_LABELS[artifact.collateralType];
    const current = groups.get(id);
    if (current) {
      current.artifacts.push(artifact);
    } else {
      groups.set(id, {
        account: groupBy === "account" ? artifact.account : undefined,
        artifacts: [artifact],
        id,
        label,
      });
    }
  });

  return [...groups.values()];
}

export function countActiveGalleryFilters(filters: GalleryFilters) {
  return filters.accountIds.length
    + filters.collateralTypes.length
    + filters.sizeCategories.length
    + (filters.projectIds?.length ?? 0)
    + (filters.dateRange === "all" ? 0 : 1);
}
