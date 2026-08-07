import {
  Confirmation,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRequest,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

export function PlanApproval({
  label,
  onAccept,
  onReject,
  onRevise,
}: {
  label: string;
  onAccept: () => void;
  onReject: () => void;
  onRevise: () => void;
}) {
  return (
    <Confirmation
      approval={{ id: "plan-approval" }}
      className={styles.planApproval}
      state="approval-requested"
    >
      <ConfirmationRequest>
        <ConfirmationTitle className={styles.planApprovalTitle}>
          <ProjectIcon name="file-text" size={16} />
          {label}
        </ConfirmationTitle>
        <ConfirmationActions className={styles.planApprovalActions}>
          <ConfirmationAction className={styles.rejectPlanButton} onClick={onReject}>
            Reject plan
          </ConfirmationAction>
          <ConfirmationAction onClick={onRevise}>Revise</ConfirmationAction>
          <ConfirmationAction className={styles.acceptPlanButton} onClick={onAccept}>
            Accept plan
          </ConfirmationAction>
        </ConfirmationActions>
      </ConfirmationRequest>
    </Confirmation>
  );
}
