import type { Metadata } from "next";
import { notFound } from "next/navigation";

export const metadata: Metadata = {
  title: "Project artifact",
};

export default function ProjectArtifactPage() {
  // No project-artifact read contract exists yet. A guessed or fixture-era
  // artifact URL must not manufacture a workspace from local preview data.
  notFound();
}
