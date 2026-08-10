import { Tool, ToolContent } from "@/components/ai-elements/tool";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { CollapsibleTrigger } from "@/components/ui/collapsible";
import type { ChatToolPart, ToolPartState } from "../model/chat-parts";
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
 * copy. It renders the receipt's own keys and values rather than a sentence the
 * backend pre-wrote, which is the rule that keeps display copy off the wire.
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

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.map(renderValue).join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function Entries({ payload }: { payload: Record<string, unknown> }) {
  const entries = Object.entries(payload);
  if (entries.length === 0) return null;
  return (
    <dl>
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key.replaceAll("_", " ")}</dt>
          <dd>{renderValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ChatToolCall({ part }: { part: ChatToolPart }) {
  const running = ACTIVE.has(part.state);
  const failed = FAILED.has(part.state);
  const label = part.toolVersion
    ? `${part.toolName}@${part.toolVersion}`
    : part.toolName;

  return (
    <Tool className={styles.toolActivity} defaultOpen={false}>
      <CollapsibleTrigger className={styles.toolActivityTrigger}>
        <ProjectIcon
          className={running ? styles.rotatingLoader : styles.statusCheck}
          name={running ? "loader" : failed ? "close" : "status-check"}
          size={running ? 13 : 14}
        />
        <span>{label}</span>
        <small>
          {running ? (
            <Shimmer duration={1.4}>{STATE_COPY[part.state]}</Shimmer>
          ) : (
            STATE_COPY[part.state]
          )}
        </small>
        <ProjectIcon className={styles.reasoningChevron} name="chevron-down" size={11} />
      </CollapsibleTrigger>
      <ToolContent className={styles.toolActivityContent}>
        {part.input ? <Entries payload={part.input} /> : null}
        {part.output ? <Entries payload={part.output} /> : null}
        {part.errorCode ? (
          <p>
            {part.errorCode}
            {part.errorReasons.length > 0 ? `: ${part.errorReasons[0]}` : ""}
          </p>
        ) : null}
      </ToolContent>
    </Tool>
  );
}
