import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Accounts",
};

export const dynamic = "force-dynamic";

export default async function AccountsPage() {
  // The shared layout keeps the account directory stable during preview navigation.
  return null;
}
