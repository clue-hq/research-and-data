import type { Metadata } from "next";
import { ApplicationShell } from "@/components/shell/application-shell";

export const metadata: Metadata = {
  title: "Projects",
};

export default function ProjectsPage() {
  return (
    <ApplicationShell activeHref="/projects">
      <main aria-label="Projects" className="h-full bg-white" />
    </ApplicationShell>
  );
}
