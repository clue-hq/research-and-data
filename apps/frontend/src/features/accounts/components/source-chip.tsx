"use client";

import { Popover } from "@base-ui/react/popover";
import { ArrowLeft, ArrowRight, ExternalLink, LockKeyhole } from "lucide-react";
import { useMemo, useState } from "react";
import type { ResearchEvidence } from "../model/research-display";
import styles from "./account-research.module.css";

export function sourceLabel(domain: string | null) {
  return domain?.replace(/^www\./, "") ?? "";
}

function evidenceDates(evidence: ResearchEvidence) {
  return [
    evidence.mediaTimestamp,
  ].filter((value): value is string => Boolean(value));
}

export function SourceIcon({ evidence }: { evidence: ResearchEvidence }) {
  // The favicon is resolved from the served domain through this app's own proxy
  // route; the served `faviconUrl` is not a precondition and is never fetched
  // directly (contract v1: "the frontend resolves favicons by domain").
  if (evidence.sourceDomain) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        alt=""
        aria-hidden="true"
        className={styles.sourceFavicon}
        src={`/api/source-favicon?domain=${encodeURIComponent(evidence.sourceDomain)}`}
      />
    );
  }

  return (
    <LockKeyhole
      aria-hidden="true"
      className={styles.sourceFaviconFallback}
      size={12}
      strokeWidth={1.5}
    />
  );
}

export function SourceChip({
  evidence,
  relatedEvidence,
}: {
  evidence: ResearchEvidence;
  relatedEvidence?: ResearchEvidence[];
}) {
  const sources = useMemo(() => {
    const records = relatedEvidence?.length ? relatedEvidence : [evidence];
    return Array.from(
      new Map(records.map((record) => [record.claimId, record])).values(),
    );
  }, [evidence, relatedEvidence]);
  const [activeIndex, setActiveIndex] = useState(0);
  const activeEvidence = sources[Math.min(activeIndex, sources.length - 1)]!;
  const firstEvidence = sources[0]!;
  const label = sourceLabel(firstEvidence.sourceDomain);
  const inlineLabel = label || "Record";
  const activeLabel = sourceLabel(activeEvidence.sourceDomain);
  const activeMeta = [
    ...evidenceDates(activeEvidence),
    activeEvidence.provider,
  ].filter((value): value is string => Boolean(value));
  const chipContent = (
    <>
      <SourceIcon evidence={firstEvidence} />
      <span className={styles.sourceName}>{inlineLabel}</span>
      {sources.length > 1 ? (
        <span className={styles.sourceCount}>+{sources.length - 1}</span>
      ) : null}
    </>
  );

  const move = (direction: -1 | 1) => {
    setActiveIndex((current) => {
      const next = current + direction;
      if (next < 0) return sources.length - 1;
      if (next >= sources.length) return 0;
      return next;
    });
  };

  return (
    <Popover.Root>
      <Popover.Trigger
        aria-label={firstEvidence.sourceUrl ? `Open ${label} source` : "View record details"}
        nativeButton={!firstEvidence.sourceUrl}
        role={firstEvidence.sourceUrl ? "link" : "button"}
        render={firstEvidence.sourceUrl ? <a href={firstEvidence.sourceUrl} target="_blank" rel="noreferrer" /> : undefined}
        className={`${styles.sourceChip} ${firstEvidence.sourceUrl ? "" : styles.privateSource}`}
        closeDelay={180}
        delay={180}
        openOnHover
      >
        {chipContent}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner align="start" collisionPadding={16} sideOffset={8} className={styles.sourcePositioner}>
          <Popover.Popup
        aria-label={`${activeLabel} source details`}
        className={styles.sourcePopover}
        initialFocus={false}
      >
        {sources.length > 1 ? (
          <span className={styles.popoverToolbar}>
            <span className={styles.popoverNav}>
              <button
                aria-label="Previous source"
                className={styles.popoverNavButton}
                onClick={() => move(-1)}
                type="button"
              >
                <ArrowLeft aria-hidden="true" size={14} strokeWidth={1.5} />
              </button>
              <button
                aria-label="Next source"
                className={styles.popoverNavButton}
                onClick={() => move(1)}
                type="button"
              >
                <ArrowRight aria-hidden="true" size={14} strokeWidth={1.5} />
              </button>
            </span>
            <span className={styles.popoverCounter}>
              {activeIndex + 1}/{sources.length}
            </span>
          </span>
        ) : null}

        <span className={styles.popoverBody}>
          <span className={styles.popoverSource}>
            <SourceIcon evidence={activeEvidence} />
            <span>{activeLabel || "Private record"}</span>
          </span>
          <span className={styles.popoverTitle}>
            {activeEvidence.title ?? (activeEvidence.sourceKind === "inference" ? "Research interpretation" : "Source record")}
          </span>
          {activeEvidence.quote ? (
            <span className={styles.popoverQuote}>
              “{activeEvidence.quote}”
            </span>
          ) : null}
          {activeEvidence.researchExcerpt && !activeEvidence.quote ? (
            <span className={styles.popoverQuote}>
              <span className={styles.sendLineChannel}>Research excerpt</span>
              {activeEvidence.researchExcerpt}
            </span>
          ) : null}
          {activeMeta.length ? (
            <span className={styles.popoverMeta}>{activeMeta.join(" · ")}</span>
          ) : null}
          {activeEvidence.sourceUrl ? (
            <a
              className={styles.popoverOpen}
              href={activeEvidence.sourceUrl}
              rel="noreferrer"
              target="_blank"
            >
              Open source
              <ExternalLink aria-hidden="true" size={12} strokeWidth={1.5} />
            </a>
          ) : null}
        </span>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

