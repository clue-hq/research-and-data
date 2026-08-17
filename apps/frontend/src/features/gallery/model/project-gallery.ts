import type {
  GalleryCollateralType,
  GallerySizeCategory,
  ProjectArtifact,
} from "@/features/projects/model/project-workspace";

export type GalleryLayout = "grid" | "list";
export type GalleryGroupBy = "none" | "account" | "type";
export type GalleryDateRange = "all" | "today" | "last-7-days" | "last-30-days";
export type GallerySort =
  | "last-viewed"
  | "edited-desc"
  | "edited-asc"
  | "name-asc"
  | "name-desc";
export type GalleryMenu = "sort" | "group" | "filter" | null;

export interface GalleryFilters {
  accountIds: string[];
  collateralTypes: GalleryCollateralType[];
  dateRange: GalleryDateRange;
  sizeCategories: GallerySizeCategory[];
}

export interface GalleryAccount {
  id: string;
  logoPath?: string;
  name: string;
}

export interface GalleryArtifact {
  account: GalleryAccount;
  collateralType: GalleryCollateralType;
  collateralTypeLabel: string;
  createdAt: string;
  editedLabel: string;
  id: string;
  imagePath: string;
  lastViewedAt: string;
  originRunId: string;
  originThreadId: string;
  size: {
    category: GallerySizeCategory;
    height: number;
    label: string;
    width: number;
  };
  source: ProjectArtifact;
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

export const COLLATERAL_TYPE_LABELS: Record<GalleryCollateralType, string> = {
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

function defaultCollateralType(artifact: ProjectArtifact): GalleryCollateralType {
  if (artifact.type === "website") return "microsite";
  if (artifact.type === "table") return "account-list";
  if (artifact.type === "presentation") return "presentation";
  return "linkedin-ad";
}

function defaultAccount(artifact: ProjectArtifact): GalleryAccount {
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
  return { id: "openai", logoPath: logo ?? "/logos/openai.svg", name: "OpenAI" };
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
  return {
    category: "square",
    height: 1080,
    label: "1080 × 1080",
    width: 1080,
  };
}

export function normalizeGalleryArtifact(artifact: ProjectArtifact): GalleryArtifact {
  const collateralType = artifact.collateralType ?? defaultCollateralType(artifact);
  const updatedAt = artifact.updatedAt ?? "2026-08-16T12:00:00.000Z";
  return {
    account: defaultAccount(artifact),
    collateralType,
    collateralTypeLabel: COLLATERAL_TYPE_LABELS[collateralType],
    createdAt: artifact.createdAt ?? updatedAt,
    editedLabel: artifact.editedLabel,
    id: artifact.id,
    imagePath: artifact.imagePath,
    lastViewedAt: artifact.lastViewedAt ?? updatedAt,
    originRunId: artifact.originRunId,
    originThreadId: artifact.originThreadId,
    size: artifact.size ?? defaultSize(artifact),
    source: artifact,
    title: artifact.title,
    updatedAt,
  };
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
    if (filters.accountIds.length > 0 && !filters.accountIds.includes(artifact.account.id)) {
      return false;
    }
    if (
      filters.collateralTypes.length > 0 &&
      !filters.collateralTypes.includes(artifact.collateralType)
    ) {
      return false;
    }
    if (
      filters.sizeCategories.length > 0 &&
      !filters.sizeCategories.includes(artifact.size.category)
    ) {
      return false;
    }
    if (!withinDateRange(artifact, filters.dateRange, now)) return false;
    if (!normalizedQuery) return true;
    return [
      artifact.title,
      artifact.account.name,
      artifact.collateralTypeLabel,
      artifact.size.label,
    ].some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
  });
}

export function sortGalleryArtifacts(
  artifacts: GalleryArtifact[],
  sort: GallerySort,
) {
  return [...artifacts].sort((left, right) => {
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
    const id = groupBy === "account" ? artifact.account.id : artifact.collateralType;
    const label = groupBy === "account"
      ? artifact.account.name
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
    + (filters.dateRange === "all" ? 0 : 1);
}
