import {
  fetchRead,
  type AuthenticatedReadRequest,
} from "@/features/accounts/data/frontend-api";
import { ProfileSchema } from "../model/profile";
import { cache } from "react";
export const getSettingsProfile = cache(
  async (request?: AuthenticatedReadRequest) => {
    return ProfileSchema.parse(
      await fetchRead("/settings/profile", {}, request),
    );
  },
);
