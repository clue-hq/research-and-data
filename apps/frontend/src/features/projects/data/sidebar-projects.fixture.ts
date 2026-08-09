import type { SidebarProject } from "../model/sidebar-project";

/**
 * Development-only project navigation records. The visual sidebar consumes
 * the typed repository result, never inline labels or route assumptions.
 */
export const sidebarProjectFixtures: SidebarProject[] = [
  {
    id: "10m-landing-page-campaign",
    title: "10x revenue campaign",
    href: "/projects/10m-landing-page-campaign",
    expanded: true,
    pinned: true,
    conversations: [
      {
        id: "thread-primary",
        title: "Landing page concepts",
        href: "/projects/10m-landing-page-campaign?thread=thread-primary",
        status: "idle",
      },
      {
        id: "thread-iteration",
        title: "Account insight report",
        href: "/projects/10m-landing-page-campaign/gallery?thread=thread-iteration",
        status: "running",
      },
    ],
  },
  {
    id: "custom-reports",
    title: "custom reports",
    href: "/projects/custom-reports",
    expanded: false,
    pinned: false,
    conversations: [
      {
        id: "thread-review",
        title: "Pipeline review",
        href: "/projects/custom-reports?thread=thread-review",
        status: "needs-input",
      },
      {
        id: "thread-approval",
        title: "Creative variants",
        href: "/projects/custom-reports?thread=thread-approval",
        status: "approval",
      },
    ],
  },
  {
    id: "conference-2026",
    title: "conference 2026",
    href: "/projects/conference-2026",
    expanded: false,
    pinned: false,
    conversations: [
      {
        id: "thread-missing-context",
        title: "Missing speaker context",
        href: "/projects/conference-2026?thread=thread-missing-context",
        status: "needs-input",
      },
    ],
  },
];
