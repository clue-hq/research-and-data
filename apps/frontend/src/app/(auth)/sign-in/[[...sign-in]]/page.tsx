import { SignIn } from "@clerk/nextjs";
import { isAuthenticationEnabled } from "@/auth/config";

export default function SignInPage() {
  if (!isAuthenticationEnabled()) {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <p>Authentication is not enabled for this frontend environment.</p>
      </main>
    );
  }
  return (
    <main className="grid min-h-screen place-items-center p-6">
      <SignIn fallbackRedirectUrl="/" path="/sign-in" routing="path" />
    </main>
  );
}
