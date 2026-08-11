import { Tool, ToolContent } from "@/components/ai-elements/tool";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { CollapsibleTrigger } from "@/components/ui/collapsible";
import type { ChatToolPart, ToolPartState } from "../model/chat-parts";
import {
  toolPresentation,
  type ToolDisplayRow,
} from "../model/chat-tool-presentation";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

/**
 * The Clue adapter for one governed tool call (charter §3.1's `tool` row).
 *
 * All seven AI Elements states are rendered, not the Completed/Running binary
 * the fixture era collapsed them to — a refused call and a denied approval look
 * nothing alike to a user, and the backend has always distinguished them.
 *
 * The output is structured JSON (§3.4), so the *adapter* chooses the disclosure
 * copy. The normal chat surface projects only explicitly allowlisted business
 * facts. Operation ids, hashes, artifact paths, refs and schema versions remain
 * in the developer inspector and never become customer-facing copy by default.
 */

const STATE_COPY: Record<ToolPartState, string> = {
  "input-streaming": "Preparing",
  "input-available": "Running",
  "approval-requested": "Waiting for approval",
  "approval-responded": "Approval recorded",
  "output-available": "Completed",
  "output-denied": "Denied",
  "output-error": "Failed",
};

const ACTIVE: ReadonlySet<ToolPartState> = new Set([
  "input-streaming",
  "input-available",
]);

const FAILED: ReadonlySet<ToolPartState> = new Set([
  "output-denied",
  "output-error",
]);

function Entries({ rows }: { rows: readonly ToolDisplayRow[] }) {
  if (rows.length === 0) return null;
  return (
    <dl>
      {rows.map((row, index) => (
        <div key={`${row.label}:${index}`}>
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ChatToolCall({ part }: { part: ChatToolPart }) {
  const running = ACTIVE.has(part.state);
  const failed = FAILED.has(part.state);
  const presentation = toolPresentation(part);
  const hasDetails = presentation.rows.length > 0 || presentation.failureMessage !== null;

  return (
    <Tool className={styles.toolActivity} defaultOpen={false}>
      <CollapsibleTrigger
        className={styles.toolActivityTrigger}
        disabled={!hasDetails}
      >
        <ProjectIcon
          className={running ? styles.rotatingLoader : styles.statusCheck}
          name={running ? "loader" : failed ? "close" : "status-check"}
          size={running ? 13 : 14}
        />
        <span>{presentation.label}</span>
        <small>
          {running ? (
            <Shimmer duration={1.4}>{STATE_COPY[part.state]}</Shimmer>
          ) : (
            STATE_COPY[part.state]
          )}
        </small>
        {hasDetails ? (
          <ProjectIcon
            className={styles.reasoningChevron}
            name="chevron-down"
            size={11}
          />
        ) : null}
      </CollapsibleTrigger>
      {hasDetails ? (
        <ToolContent className={styles.toolActivityContent}>
          <Entries rows={presentation.rows} />
          {presentation.failureMessage ? <p>{presentation.failureMessage}</p> : null}
        </ToolContent>
      ) : null}
    </Tool>
  );
}
