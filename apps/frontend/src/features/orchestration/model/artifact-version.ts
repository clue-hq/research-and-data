import type { DirectMailState } from "@/features/direct-mail/model/direct-mail";
import type { CampaignArtifact, WorkspaceState } from "./workspace";

/** Linked assets display the revision owned by their editable source record. */
export function artifactVersion(asset: CampaignArtifact, data: WorkspaceState, mail: DirectMailState | null) {
  return data.emails.find((e) => e.id === asset.emailId)?.revision
    ?? mail?.mailers.find((m) => m.id === asset.mailerId)?.revision
    ?? asset.version;
}
