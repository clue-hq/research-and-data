import {
  Source,
  Sources,
  SourcesContent,
  SourcesTrigger,
} from "@/components/ai-elements/sources";
import Image from "next/image";
import type { ProjectWorkspace } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

export function ProjectSources({
  sources,
}: {
  sources: ProjectWorkspace["conversationActivity"]["sources"];
}) {
  return (
    <Sources className={styles.projectSources} defaultOpen={false}>
      <SourcesTrigger className={styles.projectSourcesTrigger} count={sources.length}>
        <ProjectIcon name="link" size={12} />
        <span>Used {sources.length} sources</span>
        <ProjectIcon className={styles.reasoningChevron} name="chevron-down" size={11} />
      </SourcesTrigger>
      <SourcesContent className={styles.projectSourcesContent}>
        {sources.map((source) => (
          <Source href={source.href} key={source.id} title={source.label}>
            {source.logoPath ? (
              <Image
                alt=""
                height={13}
                src={source.logoPath}
                style={{ height: 13, width: 13 }}
                width={13}
              />
            ) : null}
            <span>{source.label}</span>
            <ProjectIcon name="link" size={10} />
          </Source>
        ))}
      </SourcesContent>
    </Sources>
  );
}
