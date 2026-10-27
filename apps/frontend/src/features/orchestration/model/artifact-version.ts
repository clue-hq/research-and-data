import type { DirectMailState } from "@/features/direct-mail/model/direct-mail";
import type { CampaignArtifact } from "./workspace";
export function artifactVersion(asset:CampaignArtifact,mail:DirectMailState|null) {
  const mailer=asset.kind === "note" ? mail?.mailers.find((m) => m.id === asset.mailerId) : undefined;
  return mailer?.approval?.revision ?? mailer?.revision ?? asset.version;
}
