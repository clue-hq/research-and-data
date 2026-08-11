import type { EvidenceReference } from "../model/evidence";
import { exactEvidenceSourceLabel } from "../model/evidence";
import {
  formatConfidence,
  formatFieldKeyLabel,
  formatIsoDate,
  formatToken,
} from "../model/formatting";
import { Absent } from "./account-facts";
import readability from "./account-readability.module.css";

export function EvidenceList({
  artifactHref,
  evidence,
}: {
  artifactHref: (item: EvidenceReference) => string;
  evidence: EvidenceReference[];
}) {
  if (!evidence.length) return <Absent label="No evidence recorded yet" />;

  return (
    <div className="space-y-4">
      {evidence.map((item) => {
        const confidence = formatConfidence(item.confidence);
        const observed = formatIsoDate(item.observedAt);
        const title = item.sourceTitle
          ? formatToken(item.sourceTitle)
          : "Source title unavailable";
        return (
          <article
            className="rounded-xl border border-[var(--clue-border-neutral)] p-4"
            key={item.claimId}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h3 className={readability.uiMedium}>{title}</h3>
                <p
                  className={`${readability.fieldLabel} mt-0.5 text-[var(--clue-content-subtle)]`}
                >
                  Supports {formatFieldKeyLabel(item.fieldKey)}
                </p>
              </div>
              <span
                className={`${readability.pillMedium} rounded-xl bg-[var(--clue-background-pressed)] px-2 py-1`}
              >
                {confidence ? `${confidence} confidence` : "Confidence unavailable"}
              </span>
            </div>

            {item.sourceUrl ? (
              <a
                className={`${readability.uiRegular} mt-3 block break-all underline underline-offset-2`}
                href={item.sourceUrl}
                rel="noreferrer"
                target="_blank"
              >
                {exactEvidenceSourceLabel(item.sourceUrl)}
              </a>
            ) : null}
            {item.protectedArtifactAvailable ? (
              <a
                className={`${readability.uiMedium} mt-3 inline-block underline underline-offset-2`}
                href={artifactHref(item)}
                rel="noreferrer"
                target="_blank"
              >
                Open retained evidence
              </a>
            ) : null}
            {!item.sourceUrl && !item.protectedArtifactAvailable ? (
              <p
                className={`${readability.uiRegular} mt-3 text-[var(--clue-content-subtle)]`}
              >
                The source cannot be opened from this record.
              </p>
            ) : null}

            {item.evidenceSpan ? (
              <blockquote
                className={`${readability.uiRegular} mt-3 border-l-2 border-[var(--clue-border-neutral)] pl-3`}
              >
                {item.evidenceSpan}
              </blockquote>
            ) : (
              <p
                className={`${readability.uiRegular} mt-3 text-[var(--clue-content-subtle)]`}
              >
                No display-eligible evidence span is recorded.
              </p>
            )}

            <p
              className={`${readability.fieldLabel} mt-3 break-all text-[var(--clue-content-subtle)]`}
            >
              {[
                observed,
                item.freshness === "stale"
                  ? "Past its freshness window"
                  : item.freshness === "fresh"
                    ? "Within its freshness window"
                    : null,
                `Claim ${item.claimId}`,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </article>
        );
      })}
    </div>
  );
}
