import { SidebarProjectsResponseSchema } from "../model/sidebar-project";
import type { ChatRepositories } from "./chat-repositories";

// Read-only navigation snapshot verified against the deployed Illumio workspace.
// Chat content stays in its original workspace; only its navigation is mirrored.
const projectId = "prj_f9574afe6def584da9ff7ba3cd3f35d3";
const projectHref = `/projects/${projectId}`;
const chats = [
  ["thr_0aa93764051d583b84d7c991522952f6", "Design Nordea LinkedIn ad"],
  ["thr_59dd4ebb6cce58e99e5441f2c5b03719", "Create personalised landing page"],
  ["thr_a84254ae478e5e38b63b743c31fd89fb", "Create U.S. Bank landing page"],
  ["thr_bd27d233d4ab5885ac956f5c2327deac", "Create LinkedIn ad"],
];

export function withIllumioSidebar(base: ChatRepositories): ChatRepositories {
  if (base.transport.mode !== "fixture") return base;
  return {
    ...base,
    sidebar: {
      async list() {
        return SidebarProjectsResponseSchema.parse({
          data: [{
            id: projectId,
            title: "Illumio platform marketing",
            href: projectHref,
            expanded: true,
            pinned: false,
            conversations: chats.map(([id, title]) => ({
              id,
              title,
              href: `${projectHref}/chats/${id}`,
              sourceHref: `https://app.cluehq.ai${projectHref}/chats/${id}`,
              pinned: false,
              status: "idle",
              updatedAt: "2026-11-02T23:22:00Z",
            })),
          }],
          meta: { nextCursor: null },
        });
      },
    },
  };
}
