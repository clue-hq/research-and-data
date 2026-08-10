import type { SidebarConversationStatus as Status } from "@/features/projects/model/sidebar-project";
import styles from "./project-sidebar-tree.module.css";
import { SidebarFigmaIcon } from "./sidebar-figma-icon";

export function SidebarConversationStatus({ status }: { status: Status }) {
  if (status === "idle") return null;

  if (status === "running") {
    return (
      <span aria-label="Running" className={styles.runningStatus} role="status">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          alt=""
          aria-hidden="true"
          className={styles.runningSpinner}
          height={12}
          src="/icons/spinner.svg"
          width={12}
        />
      </span>
    );
  }

  // The pinned precedence vocabulary, minus the two statuses that render
  // without a badge (`idle` above, and `running` as the spinner). `archived`
  // replaces the proposal's `review`, which no backend surface ever emits.
  const config = {
    archived: {
      icon: null,
      label: "Archived",
      style: styles.reviewBadge,
    },
    approval: {
      icon: "sidebar-approval",
      label: "Approval",
      style: styles.approvalBadge,
    },
    "needs-input": {
      icon: "sidebar-needs-input",
      label: "Needs input",
      style: styles.needsInputBadge,
    },
  }[status];

  return (
    <span className={`${styles.statusBadge} ${config.style}`}>
      {config.icon ? (
        <SidebarFigmaIcon name={config.icon} size={12} />
      ) : (
        // Existing compact check is the approved runtime derivative of the
        // Figma ready-for-review mark.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt=""
          aria-hidden="true"
          className="block size-3 shrink-0"
          height={12}
          src="/icons/projects/status-check.svg"
          width={12}
        />
      )}
      <span>{config.label}</span>
    </span>
  );
}
