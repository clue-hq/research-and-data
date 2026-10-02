import {
  fetchRead,
  type AuthenticatedReadRequest,
} from "@/features/accounts/data/frontend-api";
import { ResearchFieldsSchema, type ResearchEntity } from "../model/research-fields";

export async function getSettingsResearchFields(
  entity: ResearchEntity,
  request?: AuthenticatedReadRequest,
) {
  const result = ResearchFieldsSchema.parse(
    await fetchRead("/settings/research-fields", { searchParams: { entity } }, request),
  );
  if (result.entity !== entity) throw new Error("Research fields entity mismatch");
  return result;
}
