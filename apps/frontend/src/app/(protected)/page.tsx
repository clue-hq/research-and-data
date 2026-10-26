import type { Metadata } from "next";
import { ProjectHomeShell } from "@/features/projects/components/project-home-shell";
import { getProjectHome } from "@/features/projects/data/project-workspace.repository";

export const metadata: Metadata = {
  title: "Home",
};

export default async function Home() {
  const data = await getProjectHome();

  return <ProjectHomeShell data={data} />;
}
