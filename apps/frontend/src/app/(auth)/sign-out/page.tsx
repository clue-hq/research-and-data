import { SignOutButton } from "@clerk/nextjs";
import Link from "next/link";
import { isAuthenticationEnabled } from "@/auth/config";

export default function SignOutPage() {
  if (!isAuthenticationEnabled()) {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <Link href="/">Return to Clue</Link>
      </main>
    );
  }
  return (
    <main className="grid min-h-screen place-items-center p-6">
      <SignOutButton redirectUrl="/sign-in">
        <button type="button">Sign out of Clue</button>
      </SignOutButton>
    </main>
  );
}
