"use client";

import { useMemo, useState } from "react";
import type { ProjectDocument } from "@/features/projects/model/project-documents";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import {
  countActiveGalleryFilters, documentGalleryCards, galleryTypeOptions,
  DEFAULT_GALLERY_FILTERS,
  filterGalleryArtifacts,
  groupGalleryArtifacts,
  normalizeGalleryArtifact,
  sortGalleryArtifacts,
  type GalleryDateRange,
  type GalleryFilters,
  type GalleryGroupBy,
  type GalleryLayout,
  type GalleryMenu,
  type GallerySort,
} from "../model/project-gallery";

const NO_DOCUMENTS: ProjectDocument[] = [];

export function useProjectGalleryController(artifacts: ProjectArtifact[], documents = NO_DOCUMENTS) {
  const [layout, setLayout] = useState<GalleryLayout>("grid");
  const [groupBy, setGroupBy] = useState<GalleryGroupBy>("none");
  const [sort, setSort] = useState<GallerySort>("last-viewed");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<GalleryFilters>(DEFAULT_GALLERY_FILTERS);
  const [openMenu, setOpenMenu] = useState<GalleryMenu>(null);

  const normalizedArtifacts = useMemo(
    () => [...artifacts.map(normalizeGalleryArtifact), ...documentGalleryCards(documents)],
    [artifacts, documents],
  );
  const accounts = useMemo(() => {
    // Unattributed artifacts contribute no filter option — only real accounts
    // appear in the account filter menu.
    const index = new Map(
      normalizedArtifacts.flatMap((artifact) =>
        artifact.account ? [[artifact.account.id, artifact.account] as const] : [],
      ),
    );
    return [...index.values()];
  }, [normalizedArtifacts]);
  // Only the library's artifacts carry a project, so a project gallery's
  // controller offers no project options at all.
  const projects = useMemo(() => {
    const index = new Map(
      normalizedArtifacts.flatMap((artifact) =>
        artifact.project ? [[artifact.project.id, artifact.project] as const] : [],
      ),
    );
    return [...index.values()];
  }, [normalizedArtifacts]);
  const visibleArtifacts = useMemo(
    () => sortGalleryArtifacts(
      filterGalleryArtifacts({
        artifacts: normalizedArtifacts,
        filters,
        query,
      }),
      sort,
    ),
    [filters, normalizedArtifacts, query, sort],
  );
  const groups = useMemo(
    () => groupGalleryArtifacts(visibleArtifacts, groupBy),
    [groupBy, visibleArtifacts],
  );

  function toggleArrayFilter<Key extends "accountIds" | "collateralTypes" | "sizeCategories">(
    key: Key,
    value: GalleryFilters[Key][number],
  ) {
    setFilters((current) => {
      const values = current[key] as string[];
      return {
        ...current,
        [key]: values.includes(value as string)
          ? values.filter((candidate) => candidate !== value)
          : [...values, value],
      };
    });
  }

  return {
    accounts,
    projects,
    typeOptions: galleryTypeOptions(normalizedArtifacts),
    activeFilterCount: countActiveGalleryFilters(filters),
    filters,
    groupBy,
    groups,
    layout,
    openMenu,
    query,
    resetFilters() {
      setFilters(DEFAULT_GALLERY_FILTERS);
    },
    setDateRange(dateRange: GalleryDateRange) {
      setFilters((current) => ({ ...current, dateRange }));
    },
    setGroupBy,
    setLayout,
    setOpenMenu,
    setQuery,
    setSort,
    sort,
    toggleAccount(accountId: string) {
      toggleArrayFilter("accountIds", accountId);
    },
    toggleCollateralType(collateralType: GalleryFilters["collateralTypes"][number]) {
      toggleArrayFilter("collateralTypes", collateralType);
    },
    toggleProject(projectId: string) {
      setFilters((current) => ({
        ...current,
        projectIds: current.projectIds?.includes(projectId)
          ? current.projectIds.filter((id) => id !== projectId)
          : [...(current.projectIds ?? []), projectId],
      }));
    },
    toggleSizeCategory(sizeCategory: GalleryFilters["sizeCategories"][number]) {
      toggleArrayFilter("sizeCategories", sizeCategory);
    },
    visibleArtifactCount: visibleArtifacts.length,
  };
}

export type ProjectGalleryController = ReturnType<typeof useProjectGalleryController>;
