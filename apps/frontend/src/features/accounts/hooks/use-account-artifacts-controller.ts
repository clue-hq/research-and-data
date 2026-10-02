"use client";

import { useMemo, useState } from "react";
import type { AccountArtifact } from "../model/account-workspace";
import { accountArtifacts, filterAccountArtifacts } from "../model/account-workspace-presentation";

export function useAccountArtifactsController(artifacts: AccountArtifact[], accountId: string) {
  const [search, setSearch] = useState("");
  const [type, setType] = useState("all");
  const [sort, setSort] = useState("recent");
  const [selectedArtifact, setSelectedArtifact] =
    useState<AccountArtifact | null>(null);
  const [artifactOpen, setArtifactOpen] = useState(false);

  const scopedArtifacts = useMemo(() => accountArtifacts(artifacts, accountId), [artifacts, accountId]);
  const visibleArtifacts = useMemo(() => filterAccountArtifacts(scopedArtifacts, { search, type, sort }), [scopedArtifacts, search, type, sort]);

  return {
    artifactOpen,
    closeArtifact: () => setArtifactOpen(false),
    clearClosedArtifact: () => setSelectedArtifact(null),
    openArtifact: (artifact: AccountArtifact) => { setSelectedArtifact(artifact); setArtifactOpen(true); },
    search,
    selectedArtifact,
    setSearch,
    type,
    setType,
    sort,
    setSort,
    total: scopedArtifacts.length,
    clearFilters: () => { setSearch(""); setType("all"); },
    visibleArtifacts,
  };
}
