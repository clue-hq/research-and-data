import { fetchRead } from "./frontend-api";
import {
  DiscoveryRunStatusResponseSchema,
  type DiscoveryRunStatus,
} from "../model/discovery-status";

/** The project's latest discovery run, or `null` when none has been launched. */
export async function getDiscoveryStatus(
  projectId: string,
  read: typeof fetchRead = fetchRead,
): Promise<DiscoveryRunStatus | null> {
  const body = await read(`/projects/${encodeURIComponent(projectId)}/discovery/current`);
  return DiscoveryRunStatusResponseSchema.parse(body).data;
}
