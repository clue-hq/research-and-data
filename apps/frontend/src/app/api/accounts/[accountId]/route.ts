import { researchContextQuery } from "@/features/accounts/model/research-context";
import { getAccountDetails } from "@/features/accounts/data/account-details.repository";

export async function GET(request: Request, { params }: { params: Promise<{ accountId: string }> }) {
  const { accountId } = await params;
  const headers = { "Cache-Control": "no-store" };
  try {
    const account = await getAccountDetails(accountId, undefined, researchContextQuery(Object.fromEntries(new URL(request.url).searchParams)));
    if (!account) return Response.json({ error: "Account details not found." }, { status: 404, headers });
    return Response.json({ data: account }, { headers });
  } catch {
    return Response.json({ error: "Unable to load account details. Please try again." }, { status: 502, headers });
  }
}
