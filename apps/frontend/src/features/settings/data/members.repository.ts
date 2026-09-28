import {
  fetchRead,
  type AuthenticatedReadRequest,
} from "@/features/accounts/data/frontend-api";
import { MembersSchema } from "../model/members";
export async function getSettingsMembers(request?: AuthenticatedReadRequest) {
  return MembersSchema.parse(await fetchRead("/settings/members", {}, request));
}
