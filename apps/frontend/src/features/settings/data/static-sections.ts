// Presentation placeholders; never live-read fallbacks.
import type { StaticSettings } from "../model/settings";
export const staticSettingsSections: StaticSettings = {
  connections: [
    {
      id: "google-calendar",
      name: "Google Calendar",
      description: "Bring meetings and events into your Clue workspace.",
      logoPath: "/settings/google-calendar.svg",
      status: "connected",
    },
    {
      id: "github",
      name: "Github",
      description: "Connect repositories and development context to Clue.",
      logoPath: "/settings/github.svg",
      status: "available",
    },
    {
      id: "slack",
      name: "Slack",
      description: "Bring team conversations into your Clue workspace.",
      logoPath: "/logos/slack.svg",
      status: "available",
    },
  ],
  billing: {
    planName: "Free trial",
    planDescription: "500 credits included, expiring Aug 31, 2026.",
    remainingCredits: 300,
    totalCredits: 500,
  },
};
