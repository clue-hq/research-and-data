"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import {
  fetchBrandKitDetailFull,
  setBrandKitApproval,
  setBrandKitLogo,
  type BrandKitDetail
} from "@/engine/brandHub";
import { KitLogoPicker } from "@/components/brand/KitLogoPicker";
import { KitIdentityHeader } from "@/components/brand/KitIdentityHeader";
import { KitColorsSection } from "@/components/brand/KitColorsSection";
import { KitTypographySection } from "@/components/brand/KitTypographySection";
import { KitLogosSection } from "@/components/brand/KitLogosSection";
import { KitImagesSection } from "@/components/brand/KitImagesSection";
import { KitVoiceSection } from "@/components/brand/KitVoiceSection";
import { KitIngestionReport } from "@/components/brand/KitIngestionReport";
import { KitDiagnostics } from "@/components/brand/KitDiagnostics";
import { readIngestionReport } from "@/components/brand/kitJson";

/** Pull the source url + captured date from the ingestion report's `source`
 * block (falling back to the kit's first `sources` entry). */
function readSourceMeta(
  kitJson: any,
  ingestionReport: Record<string, any> | null
): { url: string | null; capturedAt: string | null } {
  const reportSource =
    ingestionReport && typeof ingestionReport.source === "object"
      ? (ingestionReport.source as Record<string, unknown>)
      : null;
  const fallback =
    kitJson && Array.isArray(kitJson.sources) && kitJson.sources[0]
      ? (kitJson.sources[0] as Record<string, unknown>)
      : null;
  const source = reportSource ?? fallback ?? {};
  return {
    url: typeof source.url === "string" ? source.url : null,
    capturedAt: typeof source.captured_at === "string" ? source.captured_at : null
  };
}

export default function BrandKitDetailPage(): React.ReactElement {
  const params = useParams<{ kitId: string }>();
  const kitId = typeof params?.kitId === "string" ? params.kitId : "";

  const [detail, setDetail] = useState<BrandKitDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Optimistic approval state, reconciled against the server on settle.
  const [approvedOptimistic, setApprovedOptimistic] = useState<boolean | null>(null);
  const [approveBusy, setApproveBusy] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);

  // Human logo curation: which slot the picker is open for (null = closed).
  const [logoPickerSlot, setLogoPickerSlot] = useState<string | null>(null);
  const [logoBusy, setLogoBusy] = useState(false);
  const [logoError, setLogoError] = useState<string | null>(null);

  useEffect(() => {
    if (!kitId) return;
    let cancelled = false;
    setLoadError(null);
    fetchBrandKitDetailFull({ apiBaseUrl: editorApiBaseUrl() }, kitId)
      .then((result) => {
        if (!cancelled) {
          setDetail(result);
          setApprovedOptimistic(null);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setLoadError(cause instanceof Error ? cause.message : "Could not load this kit.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [kitId]);

  const serverApproved = detail?.brandKit.approval_status === "approved";
  const approved = approvedOptimistic ?? serverApproved;

  const ingestionReport = useMemo(
    () => (detail ? readIngestionReport(detail.summary) : null),
    [detail]
  );
  const sourceMeta = useMemo(
    () => (detail ? readSourceMeta(detail.kitJson, ingestionReport) : { url: null, capturedAt: null }),
    [detail, ingestionReport]
  );

  async function handleToggleApproval(): Promise<void> {
    if (!detail || approveBusy) return;
    const nextApproved = !approved;
    setApproveBusy(true);
    setApproveError(null);
    setApprovedOptimistic(nextApproved); // optimistic pill flip
    try {
      const updated = await setBrandKitApproval(
        { apiBaseUrl: editorApiBaseUrl() },
        detail.brandKit.id,
        nextApproved ? "approved" : "draft"
      );
      setDetail(updated);
      setApprovedOptimistic(null);
    } catch (cause) {
      setApprovedOptimistic(!nextApproved); // revert the flip
      setApproveError(
        cause instanceof Error ? cause.message : "Approval change failed — try again."
      );
    } finally {
      setApproveBusy(false);
    }
  }

  async function handleSelectLogo(assetId: string): Promise<void> {
    if (!detail || logoBusy || !logoPickerSlot) return;
    setLogoBusy(true);
    setLogoError(null);
    try {
      await setBrandKitLogo({ apiBaseUrl: editorApiBaseUrl() }, detail.brandKit.id, {
        assetId,
        slot: logoPickerSlot as "primary" | "mark" | "wordmark"
      });
      // The selection published a NEW kit version — reload the whole detail.
      const updated = await fetchBrandKitDetailFull(
        { apiBaseUrl: editorApiBaseUrl() },
        detail.brandKit.id
      );
      setDetail(updated);
      setLogoPickerSlot(null);
    } catch (cause) {
      setLogoError(
        cause instanceof Error ? cause.message : "Logo selection failed — try again."
      );
    } finally {
      setLogoBusy(false);
    }
  }

  if (loadError) {
    return <p className="status-pill is-error kit-inline-error">{loadError}</p>;
  }
  if (!detail) {
    return <p className="caption kit-loading">Loading kit…</p>;
  }

  const apiBaseUrl = editorApiBaseUrl();
  const darkColorway =
    ingestionReport && typeof ingestionReport.dark_colorway === "string"
      ? ingestionReport.dark_colorway
      : null;

  return (
    <>
      <KitIdentityHeader
        kit={detail.brandKit}
        sourceUrl={sourceMeta.url}
        capturedAt={sourceMeta.capturedAt}
        approved={approved}
        approveBusy={approveBusy}
        approveError={approveError}
        onToggleApproval={handleToggleApproval}
      />
      <KitColorsSection kitJson={detail.kitJson} darkColorway={darkColorway} />
      <KitTypographySection kitJson={detail.kitJson} />
      <KitLogosSection
        kitJson={detail.kitJson}
        onChoose={(slot) => {
          setLogoError(null);
          setLogoPickerSlot(slot);
        }}
      />
      {logoPickerSlot ? (
        <section className="brand-section" aria-label="Choose logo">
          {logoError ? <p className="status-pill is-error">{logoError}</p> : null}
          <KitLogoPicker
            apiBaseUrl={apiBaseUrl}
            slot={logoPickerSlot}
            busy={logoBusy}
            onSelect={handleSelectLogo}
            onCancel={() => setLogoPickerSlot(null)}
          />
        </section>
      ) : null}
      <KitImagesSection kitJson={detail.kitJson} />
      <KitVoiceSection kitJson={detail.kitJson} ingestionReport={ingestionReport} />
      <KitIngestionReport ingestionReport={ingestionReport} />
      <KitDiagnostics diagnostics={detail.diagnostics} />
    </>
  );
}
