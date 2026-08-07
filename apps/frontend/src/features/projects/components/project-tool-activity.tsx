import {
  Tool,
  ToolContent,
} from "@/components/ai-elements/tool";
import { CollapsibleTrigger } from "@/components/ui/collapsible";
import type { ProjectMessagePart } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

type ToolPart = Extract<ProjectMessagePart, { type: "tool" }>;

function humanizeValue(value: unknown) {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}

export function ProjectToolActivity({ part }: { part: ToolPart }) {
  const complete = part.state === "output-available";

  return (
    <Tool className={styles.toolActivity} defaultOpen={false}>
      <CollapsibleTrigger className={styles.toolActivityTrigger}>
        <ProjectIcon
          className={complete ? styles.statusCheck : styles.rotatingLoader}
          name={complete ? "status-check" : "loader"}
          size={complete ? 14 : 13}
        />
        <span>{part.title}</span>
        <small>{complete ? "Completed" : "Running"}</small>
        <ProjectIcon className={styles.reasoningChevron} name="chevron-down" size={11} />
      </CollapsibleTrigger>
      <ToolContent className={styles.toolActivityContent}>
        {part.input ? (
          <dl>
            {Object.entries(part.input).map(([key, value]) => (
              <div key={key}>
                <dt>{key.replaceAll(/([A-Z])/g, " $1")}</dt>
                <dd>{humanizeValue(value)}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {part.output ? <p>{part.output}</p> : null}
      </ToolContent>
    </Tool>
  );
}
