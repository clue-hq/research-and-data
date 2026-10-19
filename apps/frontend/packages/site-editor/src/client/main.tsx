import "@clue/site-kit/jitless";
import { lockCookies } from "@clue/site-kit/cookie-lock";
import { createRoot } from "react-dom/client";
import { readBootContext } from "./boot";
import { EditorApp } from "./editor-app";
import { installSectionHost } from "./host-globals";

// Review K3-7: no section can set a cookie on the editor domain every workspace's editor shares.
// Before anything else, so before any section loads.
lockCookies();
installSectionHost();
const boot = readBootContext(
  window.location.hash,
  document.querySelector('meta[name="clue-app-origin"]')?.getAttribute("content") ?? null,
);
const container = document.getElementById("root");
// Opened directly (not framed by the app) or without a valid nonce, the editor renders nothing.
if (boot && container && window.parent !== window) {
  createRoot(container).render(<EditorApp boot={boot} />);
}
