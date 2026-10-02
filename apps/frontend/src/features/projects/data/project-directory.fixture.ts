import {
  DirectoryProjectSchema,
  projectHomeHref,
  type DirectoryProject,
} from "../model/project-directory";
import { sidebarProjectFixtures } from "./sidebar-projects.fixture";

/**
 * Development-only directory records, derived from the one sidebar fixture so
 * the two surfaces cannot describe different projects.
 *
 * The activity counts are *computed from the same conversations the sidebar
 * shows*, which is the fixture standing in for the backend's count — not a
 * second, prettier set of numbers.
 */

const descriptions: Record<string, string> = {
  "10m-landing-page-campaign":
    "Account research and personalized creative for our next revenue campaign.",
  "custom-reports": "Account insights, pipeline reviews, and custom research reports.",
  "conference-2026": "Research, planning, and account preparation for conference 2026.",
};

export const projectDirectoryFixture: DirectoryProject[] =
  sidebarProjectFixtures.map((project, index) =>
    DirectoryProjectSchema.parse({
      id: project.id,
      title: project.title,
      description: descriptions[project.id] ?? "",
      href: projectHomeHref(project.id),
      status: "active",
      pinned: project.pinned,
      brandId: "brand-clue-demo",
      productId: null,
      createdAt: `2026-08-${String(8 + index).padStart(2, "0")}T12:00:00.000Z`,
      updatedAt: `2026-08-${String(18 - index).padStart(2, "0")}T12:00:00.000Z`,
      archivedAt: null,
      activity: {
        chats: project.conversations.length,
        running: project.conversations.filter((c) => c.status === "running")
          .length,
        needsInput: project.conversations.filter(
          (c) => c.status === "needs-input",
        ).length,
      },
    }),
  );
