import Image from "next/image";
import { Building2, FileText, Image as ImageIcon, SlidersHorizontal, UserRound, Users } from "lucide-react";
import type { AccountDetail } from "../model/account-detail";
import { activityPresentation, formatAccountDate } from "../model/account-workspace-presentation";
import styles from "./account-library.module.css";

const activityIcons = { contacts: Users, summary: FileText, created: Building2, artifact: ImageIcon, updated: SlidersHorizontal };
const ACTIVITY_ICON_SIZE = 14;

export function AccountActivityFeed({
  compact = false,
  items,
  label = "Account activity",
}: {
  compact?: boolean;
  items: AccountDetail["activity"];
  label?: string;
}) {
  return (
    <ol aria-label={label} className={`${styles.activityFeed} ${compact ? styles.railFeed : ""}`}>
      {items.map((item) => {
        const Icon = activityIcons[item.kind];
        const { actorName, actorType, action } = activityPresentation(item);
        return (
          <li className={styles.activityItem} key={item.id}>
            <span className={styles.activityIcon}>
              {actorType === "clue" ? (
                <Image alt="Clue" className={styles.actorMark} height={ACTIVITY_ICON_SIZE} src="/icons/projects/clue-assistant.svg" width={ACTIVITY_ICON_SIZE} />
              ) : item.actor?.type === "person" ? (
                <UserRound aria-hidden="true" size={ACTIVITY_ICON_SIZE} strokeWidth={1.4} />
              ) : (
                <Icon aria-hidden="true" size={ACTIVITY_ICON_SIZE} strokeWidth={1.4} />
              )}
            </span>
            <p>
              {actorName ? <><span className={styles.actorName}>{actorName}</span>{" "}</> : null}
              {action}
              <span className={styles.activityTime}>
                <span aria-hidden="true"> · </span>
                {item.isSample ? <span>Sample</span> : <time dateTime={item.occurredAt} title={item.occurredAt ? formatAccountDate(item.occurredAt) : undefined}>{item.timeLabel}</time>}
              </span>
            </p>
          </li>
        );
      })}
    </ol>
  );
}
