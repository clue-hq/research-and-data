"use client";

import { useCallback, useState } from "react";
import type { ArtifactVersionsBinding } from "@/features/chat-shell/model/artifact-actions";
import type { SiteRepository } from "../data/site.repository";
import { siteVersionOptions } from "../model/site-versions";
import type { SiteVersion } from "../model/site-wire";

const VERSION_LIMIT = 20;

/** The site's versions, read when the submenu opens; a list read for an older document version is
 * not shown (the next open reads it again). A failed read shows no rows (no new failure UI). */
export function useSiteVersions({
  documentId,
  repository,
  restore,
  version,
}: {
  documentId: string | null;
  repository: SiteRepository;
  restore: (batchId: string) => void;
  version: number | null;
}): ArtifactVersionsBinding {
  const [read, setRead] = useState<{ documentId: string; list: SiteVersion[]; version: number | null } | null>(null);
  const [loading, setLoading] = useState(false);
  const open = useCallback(() => {
    if (!documentId) return;
    setLoading(true);
    void repository
      .versions(documentId, VERSION_LIMIT)
      .then((list) => setRead({ documentId, list, version }))
      .catch(() => setRead({ documentId, list: [], version }))
      .finally(() => setLoading(false));
  }, [documentId, repository, version]);
  const list = read && read.documentId === documentId && read.version === version ? read.list : [];
  const options = siteVersionOptions(list);
  const selectedId = options[0]?.id ?? null;
  const select = useCallback(
    (id: string) => {
      if (id !== selectedId) restore(id);
    },
    [restore, selectedId],
  );
  return { loading, open, options, select, selectedId };
}
