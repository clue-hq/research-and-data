export default function ProjectLoading() {
  return (
    <main
      aria-label="Loading project workspace"
      className="grid h-screen grid-cols-[480px_1fr] bg-white"
    >
      <span className="border-r border-[#e1e4e8] bg-[#fafafa]" />
      <span className="animate-pulse bg-[#f5f6f7]" />
    </main>
  );
}
