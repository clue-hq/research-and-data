import { Blocks, Cable, Network, Plus } from "lucide-react";
import type { StaticSettings } from "../model/settings";
import { ConnectionsSettings } from "./connections-settings";
import { SectionLead, SettingsCard } from "./settings-primitives";
import styles from "./settings.module.css";

const features = {
  connections: {
    icon: Cable,
    description:
      "Your favorite tools, connected to Clue. Personal connections are on the way.",
  },
  integrations: {
    icon: Blocks,
    description:
      "Bring your team's tools together. Workspace integrations are on the way.",
  },
  "mcp-server": {
    icon: Network,
    description:
      "Connect Clue to your AI tools. MCP server access is on the way.",
  },
} as const;

const integrationPreviews = [
  {
    name: "Slack",
    description: "Keep your team in the loop.",
    logo: "/logos/slack.svg",
  },
  {
    name: "Airtable",
    description: "Bring your workspace data together.",
    logo: "/logos/airtable.svg",
  },
  {
    name: "GitHub",
    description: "Connect your team's repositories.",
    logo: "/settings/github.svg",
  },
];

function IntegrationsPreview() {
  return (
    <div className={styles.sectionStack}>
      <section className={styles.connectionSection}>
        <SectionLead description="Connect the tools your team uses every day.">
          Workspace integrations
        </SectionLead>
        <div className={styles.cardStack}>
          {integrationPreviews.map((integration) => (
            <SettingsCard
              className={styles.connectionCard}
              key={integration.name}
            >
              <div className={styles.connectionIdentity}>
                <span className={styles.connectionLogo}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img alt="" src={integration.logo} />
                </span>
                <div>
                  <p className={styles.connectionName}>{integration.name}</p>
                  <p className={styles.connectionDescription}>
                    {integration.description}
                  </p>
                </div>
              </div>
              <span className={styles.previewAction}>
                Connect <Plus size={12} />
              </span>
            </SettingsCard>
          ))}
        </div>
      </section>
      <section className={styles.connectionSection}>
        <SectionLead>Connected integrations</SectionLead>
        <SettingsCard className={styles.previewEmpty}>
          Your workspace integrations will appear here.
        </SettingsCard>
      </section>
    </div>
  );
}

function McpServerPreview() {
  return (
    <div className={styles.sectionStack}>
      <section className={styles.connectionSection}>
        <SectionLead description="Give your AI tools context from your Clue workspace.">
          Connect to Clue
        </SectionLead>
        <SettingsCard className={styles.connectionCard}>
          <div className={styles.connectionIdentity}>
            <span className={styles.connectionLogo}>
              <Network size={22} strokeWidth={1.4} />
            </span>
            <div>
              <p className={styles.connectionName}>Clue MCP server</p>
              <p className={styles.connectionDescription}>
                Your workspace, available to your AI tools.
              </p>
            </div>
          </div>
          <span className={styles.previewAction}>
            Set up <Plus size={12} />
          </span>
        </SettingsCard>
      </section>
      <section className={styles.connectionSection}>
        <SectionLead>Server configuration</SectionLead>
        <SettingsCard className={styles.formCard}>
          {[
            ["Server name", "Clue workspace"],
            ["Connection URL", "Your server URL will appear here"],
            ["Access token", "••••••••••••••••••••"],
          ].map(([label, value]) => (
            <div className={styles.formRow} key={label}>
              <div className={styles.formLabel}>
                <p>{label}</p>
              </div>
              <div className={styles.previewField}>{value}</div>
            </div>
          ))}
        </SettingsCard>
      </section>
    </div>
  );
}

export function SettingsComingSoon({
  section,
  connections,
}: {
  section: keyof typeof features;
  connections: StaticSettings["connections"];
}) {
  const { icon: Icon, description } = features[section];

  return (
    <section
      aria-labelledby="settings-coming-soon-title"
      className={styles.comingSoon}
    >
      <div aria-hidden="true" className={styles.comingSoonPreview} inert>
        <div className={styles.settingsBody}>
          {section === "connections" ? (
            <ConnectionsSettings connections={connections} />
          ) : null}
          {section === "integrations" ? <IntegrationsPreview /> : null}
          {section === "mcp-server" ? <McpServerPreview /> : null}
        </div>
      </div>
      <div className={styles.comingSoonOverlay}>
        <div className={styles.comingSoonCard}>
          <span aria-hidden="true" className={styles.comingSoonIcon}>
            <Icon size={25} strokeWidth={1.35} />
          </span>
          <span className={styles.comingSoonBadge}>In development</span>
          <h2 id="settings-coming-soon-title">Coming soon</h2>
          <p>{description}</p>
        </div>
      </div>
    </section>
  );
}
