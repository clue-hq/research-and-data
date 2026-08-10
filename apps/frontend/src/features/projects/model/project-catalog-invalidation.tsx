"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

interface ProjectCatalogInvalidation {
  revision: number;
  invalidate(): void;
}

const ProjectCatalogInvalidationContext =
  createContext<ProjectCatalogInvalidation>({
    revision: 0,
    invalidate() {},
  });

/** One shell-scoped refresh signal shared by project chat and the sidebar catalog. */
export function ProjectCatalogInvalidationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [revision, setRevision] = useState(0);
  const invalidate = useCallback(() => {
    setRevision((current) => current + 1);
  }, []);
  const value = useMemo(
    () => ({ invalidate, revision }),
    [invalidate, revision],
  );
  return (
    <ProjectCatalogInvalidationContext.Provider value={value}>
      {children}
    </ProjectCatalogInvalidationContext.Provider>
  );
}

export function useProjectCatalogInvalidation(): ProjectCatalogInvalidation {
  return useContext(ProjectCatalogInvalidationContext);
}
