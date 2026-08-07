import { describe, expect, it } from "vitest";
import { EDITOR_PANEL_MODES, rightSidebarLabelForMode, type FutureEditorPanelMode } from "../editorModes";

describe("editor mode metadata", () => {
  it("keeps visible V0 panel modes ordered and labeled", () => {
    expect(EDITOR_PANEL_MODES.map((item) => item.mode)).toEqual([
      "inspector",
      "assets",
      "agent",
      "diagnostics"
    ]);
    // Export deliberately has no rail tab — the topbar popover and the
    // canvas toolbar open the export surface.
    expect(EDITOR_PANEL_MODES.some((item) => item.mode === "export")).toBe(false);
    expect(EDITOR_PANEL_MODES.find((item) => item.mode === "assets")?.ariaLabel).toBe("Assets panel");
    expect(EDITOR_PANEL_MODES.find((item) => item.mode === "diagnostics")?.ariaLabel).toBe("Diagnostics panel");
  });

  it("keeps a type seam for the future personalization mode without rendering it", () => {
    const futureMode: FutureEditorPanelMode = "personalization";
    const visibleModes = EDITOR_PANEL_MODES.map((item) => item.mode as FutureEditorPanelMode);
    expect(futureMode).toBe("personalization");
    expect(visibleModes).not.toContain(futureMode);
  });

  it("maps active panel mode to right sidebar labels", () => {
    expect(rightSidebarLabelForMode("inspector")).toBe("Inspector sidebar");
    expect(rightSidebarLabelForMode("agent")).toBe("Agent chat sidebar");
    expect(rightSidebarLabelForMode("export")).toBe("Export sidebar");
    expect(rightSidebarLabelForMode("diagnostics")).toBe("Diagnostics sidebar");
  });
});
