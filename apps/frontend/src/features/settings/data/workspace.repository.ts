import {
  fetchRead,
  type AuthenticatedReadRequest,
} from "@/features/accounts/data/frontend-api";
import { WorkspaceSchema } from "../model/workspace";
import { cache } from "react";
export const getSettingsWorkspace = cache(
  async (request?: AuthenticatedReadRequest) => {
    return WorkspaceSchema.parse(
      await fetchRead("/settings/workspace", {}, request),
    );
  },
);
