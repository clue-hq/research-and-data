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
 * lane's quiet swap); the brand is read once per document.
 *
 * A load belongs to one VISIT of a document: leaving it (for another site, or a web or ad tab) and
 * coming back shows LOADING until a fresh read lands, never the copy from the earlier visit, which
 * the working copy would otherwise adopt with an old version (review finding S2b-3). */
export function useSiteDocument({
  documentId,
  reloadNonce,
  repository,
}: {
  documentId: string | null;
  reloadNonce: number;
  repository: SiteRepository;
}): SiteDocumentLoad {
  const [state, setState] = useState<SiteDocumentLoad & { forDocumentId: string | null; visit: number }>({
    ...IDLE,
    forDocumentId: null,
    visit: 0,
  });
  // React's adjust-state-on-prop-change pattern (never a setState inside an effect).
  const [visit, setVisit] = useState<{ documentId: string | null; id: number }>({ documentId, id: 0 });
  if (visit.documentId !== documentId) setVisit({ documentId, id: visit.id + 1 });
  const visitId = visit.id;
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
        setState({ brand, error: null, forDocumentId: documentId, links, loaded, loadedAt: Date.now(), status: "ready", visit: visitId });
      } catch (error) {
        if (!live) return;
        setState({
          ...IDLE,
          error: error instanceof Error ? error.message : String(error),
          forDocumentId: documentId,
          status: "error",
          visit: visitId,
        });
      }
    })();
    return () => {
      live = false;
    };
  }, [documentId, reloadNonce, repository, visitId]);
  if (!documentId) return IDLE;
  if (state.forDocumentId !== documentId || state.visit !== visitId) return LOADING;
  return state;
}
