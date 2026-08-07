"use client";

import { ApplicationShell } from "@/components/shell/application-shell";
import { useProjectHomeController } from "../hooks/use-project-home-controller";
import type { ProjectHome } from "../model/project-workspace";
import { ProjectHomeView } from "./project-home-view";

export function ProjectHomeShell({ data }: { data: ProjectHome }) {
  const controller = useProjectHomeController(data);
  return (
    <ApplicationShell activeHref="/">
      <ProjectHomeView controller={controller} data={data} />
    </ApplicationShell>
  );
}
