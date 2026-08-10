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
        pinned: false,
        status: "idle",
        updatedAt: "2026-08-09T12:00:00Z",
      },
      {
        id: "thread-iteration",
        title: "Account insight report",
        href: "/projects/10m-landing-page-campaign/gallery?thread=thread-iteration",
        pinned: true,
        status: "running",
        updatedAt: "2026-08-09T13:00:00Z",
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
        pinned: false,
        status: "needs-input",
        updatedAt: "2026-08-08T12:00:00Z",
      },
      {
        id: "thread-approval",
        title: "Creative variants",
        href: "/projects/custom-reports?thread=thread-approval",
        pinned: false,
        status: "approval",
        updatedAt: "2026-08-08T13:00:00Z",
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
        pinned: false,
        status: "needs-input",
        updatedAt: "2026-08-07T12:00:00Z",
      },
    ],
  },
];
