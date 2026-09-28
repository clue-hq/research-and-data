import { ArrowUpRight, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { StaticSettings } from "../model/settings";
import styles from "./settings.module.css";
import { SectionLead, SettingsCard } from "./settings-primitives";

function ConnectionCard({
  connection,
}: {
  connection: StaticSettings["connections"][number];
}) {
  return (
    <SettingsCard className={styles.connectionCard}>
      <div className={styles.connectionIdentity}>
        <span className={styles.connectionLogo}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="" src={connection.logoPath} />
        </span>
        <div>
          <p className={styles.connectionName}>{connection.name}</p>
          <p className={styles.connectionDescription}>
            {connection.description}
          </p>
        </div>
      </div>
      {connection.status === "connected" ? (
        <Button size="sm" variant="secondary">
          Connected
          <ChevronDown size={12} strokeWidth={1.4} />
        </Button>
      ) : (
        <Button size="sm" variant="secondary">
          Connect
          <ArrowUpRight size={12} strokeWidth={1.4} />
        </Button>
      )}
    </SettingsCard>
  );
}

export function ConnectionsSettings({
  connections,
}: {
  connections: StaticSettings["connections"];
}) {
  const available = connections.filter(
    (connection) => connection.status === "available",
  );
  const connected = connections.filter(
    (connection) => connection.status === "connected",
  );

  return (
    <div className={styles.sectionStack}>
      <section className={styles.connectionSection}>
        <SectionLead>Available connections</SectionLead>
        <div className={styles.cardStack}>
          {available.map((connection) => (
            <ConnectionCard connection={connection} key={connection.id} />
          ))}
        </div>
      </section>
      <section className={styles.connectionSection}>
        <SectionLead>Connected accounts</SectionLead>
        <div className={styles.cardStack}>
          {connected.map((connection) => (
            <ConnectionCard connection={connection} key={connection.id} />
          ))}
        </div>
      </section>
    </div>
  );
}
