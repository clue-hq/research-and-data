"use client";
import { useState } from "react";
import { readLocalAsset } from "../data/direct-mail.uploads";
import type { CardAsset } from "../model/direct-mail";
import type { DirectMailController } from "./use-direct-mail";

export function useCardLibrary(c: DirectMailController) {
  const [kind, setKind] = useState<"card" | "font" | null>(null);
  const [name, setName] = useState("");
  const [frontUrl, setFront] = useState<string | null>(null);
  const [backUrl, setBack] = useState<string | null>(null);
  const [fontUrl, setFont] = useState<string | null>(null);
  const [area, setArea] = useState({ x: 10, y: 12, width: 80, height: 78 });
  const [paper, setPaper] = useState<"white" | "cream">("white");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  function open(next: "card" | "font") { setKind(next); setName(""); setFront(null); setBack(null); setFont(null); setError(null); setArea({ x: 10, y: 12, width: 80, height: 78 }); }
  async function upload(file: File | undefined, side: "front" | "back" | "font") {
    if (!file) return;
    setLoading(true); setError(null);
    try { const url = await readLocalAsset(file, side === "font" ? "font" : "card"); if (side === "font") setFont(url); else if (side === "front") setFront(url); else setBack(url); }
    catch (error) { setError(error instanceof Error ? error.message : "The file could not be read. Choose another file."); }
    finally { setLoading(false); }
  }
  const card: CardAsset = { id: "upload-preview", version: 1, name: name || "New card", frontUrl, backUrl, writingArea: area, paper, productionReady: false };
  const validArea = area.x + area.width <= 100 && area.y + area.height <= 100;
  const valid = name.trim() && (kind === "card" ? frontUrl && validArea : fontUrl) && !loading;
  async function save() {
    if (!valid) return;
    const id = crypto.randomUUID();
    const result = kind === "card" ? await c.run(() => c.repository.addCard({ ...card, id: `card-${id}`, name: name.trim() })) : await c.run(() => c.repository.addStyle({ id: `style-${id}`, version: 1, name: name.trim(), family: `ClueUpload${id.replaceAll("-", "")}`, sourceUrl: fontUrl, productionReady: false }));
    if (result) setKind(null);
  }
  return { kind, open, close: () => setKind(null), name, setName, card, fontUrl, area, setArea, paper, setPaper, error, loading, upload, save, valid, validArea };
}
