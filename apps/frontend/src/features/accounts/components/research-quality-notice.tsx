import Link from "next/link";
import type { ResearchQuality } from "../model/research-context";
import { withResearchContext } from "../model/research-context";
import styles from "./account-research.module.css";

const labels: Record<ResearchQuality["qualityState"], string> = {
  researching: "Research in progress", provisional: "Provisional research",
  reconciled: "Research reconciled", partial: "Research partially complete",
  needs_review: "Research needs review", suspended: "Research paused",
  privacy_stopped: "Research unavailable", context_required: "Choose a research project",
  legacy: "Earlier research",
};

export function ResearchQualityNotice({ quality, path }: { quality?: ResearchQuality | null; path: string }) {
  if (!quality) return null;
  return <aside className={styles.readingSection} aria-label="Research quality">
    <p>{labels[quality.qualityState]}{quality.refreshPending ? " · Updated synthesis pending" : ""}</p>
    {quality.gaps.length > 0 && <ul>{quality.gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul>}
    {quality.contexts.length > 1 && <nav aria-label="Research projects">
      {quality.contexts.map((context) => <p key={`${context.projectName}:${context.contextId}`}>
        <Link href={withResearchContext(path, context)} aria-current={quality.contextId === context.contextId ? "page" : undefined}>
          {context.projectName}
        </Link>
      </p>)}
    </nav>}
  </aside>;
}
