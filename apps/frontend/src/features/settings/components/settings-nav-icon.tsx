import {
  ArrowLeft,
  Blocks,
  Box,
  BriefcaseBusiness,
  Cable,
  Globe2,
  Network,
  ReceiptText,
  UserRound,
  UsersRound,
} from "lucide-react";
import type { SettingsNavigationIcon } from "../config/settings-navigation";

const icons = {
  back: ArrowLeft,
  profile: UserRound,
  connections: Cable,
  mcp: Network,
  workspace: BriefcaseBusiness,
  members: UsersRound,
  integrations: Blocks,
  pages: Globe2,
  "data-model": Box,
  billing: ReceiptText,
} satisfies Record<SettingsNavigationIcon, typeof ArrowLeft>;

export function SettingsNavIcon({ name }: { name: SettingsNavigationIcon }) {
  const Icon = icons[name];

  return <Icon aria-hidden="true" size={14} strokeWidth={1.35} />;
}
