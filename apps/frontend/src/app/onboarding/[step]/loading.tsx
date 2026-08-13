export default function OnboardingLoading() {
  return (
    <div
      aria-label="Loading onboarding"
      className="grid min-h-dvh place-items-center bg-white"
      role="status"
    >
      <span className="size-4 animate-spin rounded-full border border-[#d8dcd8] border-t-[#4f584c]" />
    </div>
  );
}
