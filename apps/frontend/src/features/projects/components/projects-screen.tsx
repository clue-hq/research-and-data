"use client";

import { useProjectsScreenController } from "../hooks/use-projects-screen-controller";
import { ProjectsDirectoryView } from "./projects-directory-view";
import { ProjectOverviewView } from "./project-overview-view";
import { ProjectDirectoryDialog } from "./project-directory-dialog";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import styles from "./projects-directory.module.css";

export function ProjectsScreen({
  projectId,
  initialPrompt,
}: {
  projectId?: string;
  initialPrompt?: string;
}) {
  const controller = useProjectsScreenController(projectId, initialPrompt);
  return <>
    <main className={styles.screen} aria-label={projectId ? "Project home" : "Projects"}>
      {!controller.loaded ? <div className={styles.loading} role="status"><span className={styles.skeleton} />Loading projects…</div> : !controller.data ? <div className={styles.empty}><h1>Projects couldn’t be loaded</h1><p>{controller.error}</p><Button onClick={() => void controller.retry()} size="sm">Try again</Button></div> : projectId && !controller.project ? <div className={styles.empty}><h1>Project not found</h1><p>This project isn’t available in this workspace.</p><Link href="/projects">Back to Projects</Link></div> : projectId ? <ProjectOverviewView controller={controller} /> : <ProjectsDirectoryView controller={controller} />}
      {controller.error && controller.data && !controller.dialog ? <div className={styles.error} role="alert">{controller.error}<Button variant="transparent" size="sm" onClick={controller.clearError}>Dismiss</Button></div> : null}
    </main>
    <ProjectDirectoryDialog controller={controller} />
  </>;
}
