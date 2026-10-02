import { NextRequest } from "next/server";

// The upstream is fixed. A caller can supply a domain label, never a fetch URL.
export async function GET(request: NextRequest) {
  const domain = request.nextUrl.searchParams.get("domain") ?? "";
  if (domain.length > 253 || !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/i.test(domain)) {
    return new Response(null, { status: 400 });
  }
  try {
    const response = await fetch(`https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32`, {
      next: { revalidate: 604800 }, signal: AbortSignal.timeout(8000),
    });
    const type = response.headers.get("content-type") ?? "";
    if (!response.ok || !/^image\/(png|x-icon|vnd.microsoft.icon|jpeg|webp)/.test(type)) throw new Error("Favicon unavailable");
    return new Response(await response.arrayBuffer(), { headers: {
      "Content-Type": type, "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400", "X-Content-Type-Options": "nosniff",
    } });
  } catch {
    // A neutral link symbol is a fallback, not a fabricated company logo.
    return new Response('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="none" stroke="#8a8a8a"/><path d="M2 8h12M8 2v12" stroke="#8a8a8a"/></svg>', {
      headers: { "Content-Type": "image/svg+xml", "Cache-Control": "public, max-age=60", "X-Content-Type-Options": "nosniff" },
    });
  }
}
