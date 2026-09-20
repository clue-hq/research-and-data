import type { Metadata } from "next";
import { ProjectsScreen } from "@/features/projects/components/projects-screen";

export const metadata: Metadata = {
  title: "Projects",
};

export default function ProjectsPage() {
  return <ProjectsScreen />;
}
