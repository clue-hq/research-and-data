import Link from "next/link";

export default function Home() {
  return (
    <main className="p-10 font-sans">
      <h1 className="text-2xl font-semibold">Puck spike</h1>
      <ul className="mt-4 list-disc pl-6">
        <li><Link className="underline" href="/edit/probe">Editor: probe</Link></li>
        <li><Link className="underline" href="/s/probe">Published: probe</Link></li>
      </ul>
    </main>
  );
}
