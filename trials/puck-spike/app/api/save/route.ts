import { NextResponse } from "next/server";
import { writePage } from "@/lib/store";

export async function POST(request: Request) {
  const { site, route, data } = await request.json();
  writePage(String(site), String(route), data);
  return NextResponse.json({ ok: true });
}
