import type { DirectMailState } from "@/features/direct-mail/model/direct-mail";
import type { CampaignArtifact } from "./workspace";
export function artifactVersion(asset:CampaignArtifact,mail:DirectMailState|null) {
  return mail?.mailers.find((m) => m.id === asset.mailerId)?.revision ?? asset.version;
}
