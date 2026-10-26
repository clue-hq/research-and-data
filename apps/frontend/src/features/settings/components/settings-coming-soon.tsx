import { Cable, Network, Plus } from "lucide-react";
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
  "mcp-server": {
    icon: Network,
    description:
      "Connect Clue to your AI tools. MCP server access is on the way.",
  },
} as const;

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
