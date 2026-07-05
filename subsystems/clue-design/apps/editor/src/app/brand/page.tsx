"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import {
  fetchBrandKitDetailFull,
  fetchBrandKitList,
  type BrandKitListEntry
} from "@/engine/brandHub";
import { KitListCard } from "@/components/brand/KitListCard";
import { signatureColors } from "@/components/brand/kitJson";

export default function BrandKitListPage(): React.ReactElement {
  const [kits, setKits] = useState<BrandKitListEntry[] | null>(null);
  const [palettes, setPalettes] = useState<Record<string, string[]>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const apiBaseUrl = editorApiBaseUrl();
    setError(null);
    fetchBrandKitList({ apiBaseUrl })
      .then((list) => {
        if (cancelled) return;
        setKits(list);
        // The palette strip is each card's identity — fetch details lazily and
        // fill strips in as they arrive (a miss just leaves that card plain).
        for (const kit of list) {
          fetchBrandKitDetailFull({ apiBaseUrl }, kit.id)
            .then((detail) => {
              if (cancelled) return;
              const colors = signatureColors(detail.kitJson);
              if (colors.length > 0) {
                setPalettes((prev) => ({ ...prev, [kit.id]: colors }));
              }
            })
            .catch(() => {
              /* strip stays plain */
            });
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setKits([]);
          setError(cause instanceof Error ? cause.message : "Could not load brand kits.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <header className="kit-page-head">
        <div>
          <p className="eyebrow">Brand kits</p>
          <h1 className="display">Your brand, distilled.</h1>
        </div>
        <Link className="btn btn-primary" href="/brand/ingest">
          Ingest a brand
        </Link>
      </header>

      {error ? <p className="status-pill is-error kit-inline-error">{error}</p> : null}

      {kits === null ? (
        <p className="caption kit-loading">Loading kits…</p>
      ) : kits.length === 0 ? (
        <Link href="/brand/ingest" className="dropzone kit-empty" data-testid="kit-empty">
          <span className="title">No kits yet.</span>
          <span className="caption">Ingest a website, a brand PDF, or a set of assets to begin.</span>
        </Link>
      ) : (
        <div className="grid-cards kit-list-grid">
          {kits.map((kit) => (
            <KitListCard key={kit.id} kit={kit} palette={palettes[kit.id]} />
          ))}
        </div>
      )}
    </>
  );
}
