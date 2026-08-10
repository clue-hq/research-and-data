"use client";

import { useMemo, useState } from "react";
import type { AccountArtifact } from "../model/account-workspace";

export function useAccountArtifactsController(artifacts: AccountArtifact[]) {
  const [search, setSearch] = useState("");
  const [selectedArtifact, setSelectedArtifact] =
    useState<AccountArtifact | null>(null);

  const visibleArtifacts = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return artifacts;

    return artifacts.filter((artifact) =>
      artifact.title.toLowerCase().includes(query),
    );
  }, [artifacts, search]);

  return {
    closeArtifact: () => setSelectedArtifact(null),
    openArtifact: setSelectedArtifact,
    search,
    selectedArtifact,
    setSearch,
    visibleArtifacts,
  };
}
