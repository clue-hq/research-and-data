import type { Metadata } from "next";
import { CrmCallback } from "@/features/integrations/components/crm-callback";

export const metadata: Metadata = {
  title: "Connecting your CRM",
};

export const dynamic = "force-dynamic";

interface CrmCallbackPageProps {
  searchParams: Promise<{
    request?: string;
    status?: string;
    connected_account_id?: string;
  }>;
}

/** Composio's return page after the CRM consent screen (CRM integration, R-3.10). */
export default async function CrmCallbackPage({ searchParams }: CrmCallbackPageProps) {
  const params = await searchParams;
  return (
    <CrmCallback
      connectedAccountId={params.connected_account_id ?? null}
      requestId={params.request ?? null}
      status={params.status ?? null}
    />
  );
}
