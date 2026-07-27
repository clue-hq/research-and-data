"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronDown } from "lucide-react";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import {
  fetchBrandKitDetailFull,
  fetchBrandKitList,
  type BrandKitListEntry
} from "@/engine/brandHub";
import { signatureColors } from "@/components/brand/kitJson";
import { createWebDocument, webPromptStorageKey } from "@/engine/webDocuments";

type ProjectType = "design" | "web";

/** Derive a document title from the brief: first ~50 chars, else a fallback. */
function deriveTitle(prompt: string): string {
  const trimmed = prompt.trim();
  if (!trimmed) return "Untitled website";
  return trimmed.slice(0, 50);
}

/** The brand-kit selector: a chip trigger opening a popover listbox. Each row
 * shows the kit name + its signature palette (the card's identity, per the
 * /brand list). "No kit" is always offered and is the default. */
function BrandKitSelect({
  kits,
  palettes,
  selectedId,
  onSelect
}: {
  kits: BrandKitListEntry[] | null;
  palettes: Record<string, string[]>;
  selectedId: string | null;
  onSelect: (kitId: string | null) => void;
}): React.ReactElement {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const selected = selectedId ? kits?.find((kit) => kit.id === selectedId) ?? null : null;

  const dots = (palette: string[] | undefined) =>
    palette && palette.length > 0 ? (
      <span className="new-kit-dots" aria-hidden>
        {palette.slice(0, 5).map((hex, index) => (
          <span key={`${hex}-${index}`} style={{ backgroundColor: hex }} />
        ))}
      </span>
    ) : null;

  return (
    <div className="new-kit-select" ref={rootRef}>
      <button
        type="button"
        className="new-kit-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span>{selected ? selected.name : "No kit"}</span>
        {selected ? dots(palettes[selected.id]) : null}
        <ChevronDown size={14} className="new-kit-trigger-chevron" aria-hidden />
      </button>
      {open ? (
        <ul className="new-kit-menu" role="listbox">
          <li>
            <button
              type="button"
              role="option"
              aria-selected={selectedId === null}
              className={`new-kit-option${selectedId === null ? " is-selected" : ""}`}
              onClick={() => {
                onSelect(null);
                setOpen(false);
              }}
            >
              <span className="new-kit-option-name">No kit</span>
            </button>
          </li>
          {kits === null ? (
            <li className="new-kit-empty">Loading kits…</li>
          ) : kits.length === 0 ? (
            <li className="new-kit-empty">No brand kits yet.</li>
          ) : (
            kits.map((kit) => (
              <li key={kit.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={selectedId === kit.id}
                  className={`new-kit-option${selectedId === kit.id ? " is-selected" : ""}`}
                  onClick={() => {
                    onSelect(kit.id);
                    setOpen(false);
                  }}
                >
                  <span className="new-kit-option-name">{kit.name}</span>
                  {dots(palettes[kit.id])}
                </button>
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}

export default function NewProjectPage(): React.ReactElement {
  const router = useRouter();
  const [projectType, setProjectType] = useState<ProjectType>("design");
  const [prompt, setPrompt] = useState("");
  const [kits, setKits] = useState<BrandKitListEntry[] | null>(null);
  const [palettes, setPalettes] = useState<Record<string, string[]>>({});
  const [selectedKitId, setSelectedKitId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Kit list + lazy palette strips, mirroring the /brand list: fetch the list,
  // then fill each kit's signature colors in as its detail arrives (a miss just
  // leaves that row name-only).
  useEffect(() => {
    let cancelled = false;
    const apiBaseUrl = editorApiBaseUrl();
    fetchBrandKitList({ apiBaseUrl })
      .then((list) => {
        if (cancelled) return;
        setKits(list);
        for (const kit of list) {
          fetchBrandKitDetailFull({ apiBaseUrl }, kit.id)
            .then((detail) => {
              if (cancelled) return;
              const colors = signatureColors(detail.kitJson);
              if (colors.length > 0) {
                setPalettes((prev) => ({ ...prev, [kit.id]: colors }));
              }
            })
            .catch(() => {
              /* strip stays name-only */
            });
        }
      })
      .catch(() => {
        // The kit selector is a nice-to-have; an API hiccup must not block the
        // gate. Empty list still offers "No kit".
        if (!cancelled) setKits([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreate = async () => {
    if (submitting) return;
    setError(null);

    if (projectType === "design") {
      // P0: the design path opens the existing blank canvas; the prompt is not
      // wired through yet.
      router.push("/");
      return;
    }

    setSubmitting(true);
    try {
      const selectedKit = selectedKitId
        ? kits?.find((kit) => kit.id === selectedKitId) ?? null
        : null;
      const { documentId } = await createWebDocument(
        { apiBaseUrl: editorApiBaseUrl() },
        {
          title: deriveTitle(prompt),
          brandKitRef: selectedKit
            ? { id: selectedKit.id, version: selectedKit.version }
            : undefined
        }
      );
      // Stash the brief for the web shell to pick up (generation lands next slice).
      try {
        window.sessionStorage.setItem(webPromptStorageKey(documentId), prompt);
      } catch {
        /* private mode / storage disabled — the shell just shows no queued brief */
      }
      router.push(`/web/${documentId}`);
    } catch (cause: unknown) {
      setSubmitting(false);
      setError(cause instanceof Error ? cause.message : "Could not start this website.");
    }
  };

  return (
    <>
      <header className="new-topbar">
        <Link href="/new" className="new-wordmark">
          Clue<span className="dot">.</span>
        </Link>
        <nav>
          <Link href="/brand">Brand</Link>
          <Link href="/">Editor</Link>
        </nav>
      </header>

      <main className="new-main">
        <div className="new-head">
          <p className="eyebrow">New project</p>
          <h1 className="display">What are we making today?</h1>
        </div>

        <div className="new-type-row" role="tablist" aria-label="Project type">
          <button
            type="button"
            role="tab"
            aria-selected={projectType === "design"}
            className={`chip new-type-chip${projectType === "design" ? " is-selected" : ""}`}
            onClick={() => setProjectType("design")}
          >
            Design
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={projectType === "web"}
            className={`chip new-type-chip${projectType === "web" ? " is-selected" : ""}`}
            onClick={() => setProjectType("web")}
          >
            Website<span className="new-type-beta">beta</span>
          </button>
        </div>

        <div className="brand-card new-composer">
          <div className="new-composer-head">
            <span className="new-composer-head-label">Brand kit</span>
            <BrandKitSelect
              kits={kits}
              palettes={palettes}
              selectedId={selectedKitId}
              onSelect={setSelectedKitId}
            />
          </div>
          <textarea
            className="new-prompt"
            placeholder={
              projectType === "web"
                ? "Describe the website — who it's for, what it should say, the vibe."
                : "Describe the design you want to make."
            }
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
          />
          <div className="new-composer-actions">
            {error ? <p className="status-pill is-error">{error}</p> : null}
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleCreate}
              disabled={submitting}
            >
              {submitting ? "Creating…" : "Create"}
            </button>
          </div>
        </div>
      </main>
    </>
  );
}
