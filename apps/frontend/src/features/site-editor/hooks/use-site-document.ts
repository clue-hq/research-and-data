"use client";

import { useEffect, useRef, useState } from "react";
import type { BrandData } from "@clue/site-kit";
import type { SectionLink } from "@clue/site-kit/site-document";
import type { SiteRepository } from "../data/site.repository";
import type { LoadedSite } from "../model/site-wire";

export interface SiteDocumentLoad {
  brand: BrandData | null;
  error: string | null;
  links: SectionLink[];
  loaded: LoadedSite | null;
  loadedAt: number;
  status: "idle" | "loading" | "ready" | "error";
}

const IDLE: SiteDocumentLoad = { brand: null, error: null, links: [], loaded: null, loadedAt: 0, status: "idle" };
const LOADING: SiteDocumentLoad = { ...IDLE, status: "loading" };

/** The open site, its brand and its agent-section links, refetched whenever `reloadNonce` moves. A
 * reload of the SAME document keeps the previous load on screen until the new one lands (the web
 * lane's quiet swap); the brand is read once per document. */
export function useSiteDocument({
  documentId,
  reloadNonce,
  repository,
}: {
  documentId: string | null;
  reloadNonce: number;
  repository: SiteRepository;
}): SiteDocumentLoad {
  const [state, setState] = useState<SiteDocumentLoad & { forDocumentId: string | null }>({ ...IDLE, forDocumentId: null });
  const brandRef = useRef<{ brand: BrandData; documentId: string } | null>(null);
  useEffect(() => {
    if (!documentId) return;
    let live = true;
    void (async () => {
      try {
        const loaded = await repository.get(documentId);
        const cachedBrand = brandRef.current?.documentId === documentId ? brandRef.current.brand : null;
        const [brand, links] = await Promise.all([
          cachedBrand ? Promise.resolve(cachedBrand) : repository.getBrand(documentId),
          Object.keys(loaded.site.agent_sections).length > 0 ? repository.sectionLinks(documentId) : Promise.resolve([]),
        ]);
        if (!live) return;
        brandRef.current = { brand, documentId };
        setState({ brand, error: null, forDocumentId: documentId, links, loaded, loadedAt: Date.now(), status: "ready" });
      } catch (error) {
        if (!live) return;
        setState({ ...IDLE, error: error instanceof Error ? error.message : String(error), forDocumentId: documentId, status: "error" });
      }
    })();
    return () => {
      live = false;
    };
  }, [documentId, reloadNonce, repository]);
  if (!documentId) return IDLE;
  if (state.forDocumentId !== documentId) return LOADING;
  return state;
}
