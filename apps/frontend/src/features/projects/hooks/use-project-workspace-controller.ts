import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type {
  ArtifactFilter,
  ArtifactSort,
  ArtifactSurface,
  GalleryLayout,
  InspectorSelection,
  PreviewDevice,
  ProjectPhase,
  ProjectWorkspace,
} from "../model/project-workspace";

/**
 * The artifact half of the project workspace.
 *
 * **What left this hook in slice D5.** The conversation did: the transcript, the
 * threads, message submission, and every `setTimeout` that used to advance a
 * six-value phase enum and manufacture a transcript from it. Those are
 * `use-project-chat-controller` now, backed by real turns, and the deleted
 * timers are the charter's "production progression is event-driven; prototype
 * timeouts must not become the backend lifecycle model".
 *
 * **What `previewSurface` still is.** The `?phase=` query parameter documented
 * as *frontend-only preview state* in `docs/api-contracts/projects.md` — it
 * opens an approved artifact-side screen directly. It is set from that
 * parameter and from explicit user clicks, never from a timer, and no message
 * anywhere is derived from it.
 */
export interface ProjectWorkspaceInitialState {
  artifactId?: string;
  entityIds?: string[];
  modelId?: string;
  /** The artifact-side preview screen, from `?phase=`. Not a conversation state. */
  phase: ProjectPhase;
  prompt?: string;
  surface: ArtifactSurface;
  threadId?: string;
}

export function useProjectWorkspaceController({
  initial,
  workspace,
}: {
  initial: ProjectWorkspaceInitialState;
  workspace: ProjectWorkspace;
}) {
  const router = useRouter();
  const [previewSurface, setPreviewSurface] = useState(initial.phase);
  const [surface, setSurface] = useState(initial.surface);
  const [prompt, setPromptState] = useState(initial.prompt ?? "");
  const [selectedModelId, setSelectedModelId] = useState(
    initial.modelId && workspace.models.some((model) => model.id === initial.modelId)
      ? initial.modelId
      : (workspace.defaultModelId ?? ""),
  );
  const [selectedArtifactId, setSelectedArtifactId] = useState(
    initial.artifactId ?? workspace.artifacts[2]?.id ?? workspace.artifacts[0]?.id ?? "",
  );
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [selectedEntityIds, setSelectedEntityIds] = useState(() =>
    (initial.entityIds ?? []).filter((id) =>
      workspace.contextEntities.some((entity) => entity.id === id),
    ),
  );
  const [galleryLayout, setGalleryLayout] = useState<GalleryLayout>("grid");
  const [galleryQuery, setGalleryQuery] = useState("");
  const [artifactFilter, setArtifactFilter] = useState<ArtifactFilter>("all");
  const [artifactSort, setArtifactSort] = useState<ArtifactSort>("last-viewed");
  const [groupByAccount, setGroupByAccount] = useState(false);
  const [focusPane, setFocusPane] = useState<"artifacts" | "conversation" | "split">("split");
  const [previewDevice, setPreviewDevice] = useState<PreviewDevice>("desktop");
  const [previewZoom, setPreviewZoom] = useState(50);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorSelection, setInspectorSelection] =
    useState<InspectorSelection>("canvas");
  const [questionnaire, setQuestionnaire] = useState({
    primaryActionId: workspace.questionnaire?.primaryAction.defaultChoiceId ?? "",
    secondaryActionId:
      workspace.questionnaire?.secondaryAction.defaultChoiceId ?? "",
    targetAccounts: workspace.questionnaire?.targetAccounts.defaultValue ?? "",
    themeId: workspace.questionnaire?.theme.defaultChoiceId ?? "",
  });
  const [editableHeadline, setEditableHeadline] = useState(
    workspace.artifacts.find((artifact) => artifact.websiteContent)?.websiteContent?.headline ?? "",
  );
  const [headlineSize, setHeadlineSize] = useState(48);
  const [headlineColor, setHeadlineColor] = useState("#111318");
  const [headlineAlign, setHeadlineAlign] = useState<"left" | "center" | "right">(
    "center",
  );
  const [headlineFont, setHeadlineFont] = useState<"Arial" | "Inter" | "Satoshi">("Inter");
  const [headlineWeight, setHeadlineWeight] = useState<400 | 500 | 600>(600);
  const [ctaLabel, setCtaLabel] = useState(
    workspace.artifacts.find((artifact) => artifact.websiteContent)?.websiteContent?.ctaLabel ?? "",
  );
  const [heroImageFit, setHeroImageFit] = useState<"fill" | "fit">("fill");
  const [heroImagePath, setHeroImagePath] = useState(
    workspace.artifacts.find((artifact) => artifact.websiteContent)?.websiteContent?.heroImagePath ?? "",
  );
  const [heroImageRadius, setHeroImageRadius] = useState(28);
  const heroImageObjectUrl = useRef<string | null>(null);

  const selectedModel = useMemo(
    () =>
      workspace.models.find((model) => model.id === selectedModelId) ??
      workspace.models[0],
    [selectedModelId, workspace.models],
  );
  const selectedArtifact = useMemo(
    () =>
      workspace.artifacts.find((artifact) => artifact.id === selectedArtifactId) ??
      workspace.artifacts[0],
    [selectedArtifactId, workspace.artifacts],
  );
  const selectedEntities = useMemo(
    () =>
      selectedEntityIds
        .map((id) => workspace.contextEntities.find((entity) => entity.id === id))
        .filter((entity): entity is ProjectWorkspace["contextEntities"][number] =>
          Boolean(entity),
        ),
    [selectedEntityIds, workspace.contextEntities],
  );
  const galleryArtifacts = useMemo(() => {
    const query = galleryQuery.trim().toLocaleLowerCase();
    const filtered = workspace.artifacts.filter((artifact) => {
      if (artifactFilter !== "all" && artifact.type !== artifactFilter) return false;
      if (!query) return true;
      return `${artifact.title} ${artifact.editedLabel}`.toLocaleLowerCase().includes(query);
    });
    return artifactSort === "name"
      ? [...filtered].sort((left, right) => left.title.localeCompare(right.title))
      : filtered;
  }, [artifactFilter, artifactSort, galleryQuery, workspace.artifacts]);

  useEffect(() => {
    return () => {
      if (heroImageObjectUrl.current) URL.revokeObjectURL(heroImageObjectUrl.current);
    };
  }, []);

  function syncRoute(artifactId?: string) {
    if (artifactId) {
      router.replace(`/projects/${workspace.id}/artifacts/${artifactId}`, {
        scroll: false,
      });
      return;
    }
    router.replace(`/projects/${workspace.id}/gallery`, { scroll: false });
  }

  function openArtifact(artifactId: string) {
    setSelectedArtifactId(artifactId);
    setSurface("artifact");
    setInspectorOpen(false);
    setInspectorSelection("canvas");
    syncRoute(artifactId);
  }

  function openGallery() {
    setSurface("gallery");
    setPreviewSurface("conversation");
    setInspectorOpen(false);
    syncRoute();
  }

  function setPrompt(value: string) {
    setPromptState(value);
  }

  function selectEntity(entityId: string) {
    setSelectedEntityIds((current) =>
      current.includes(entityId) ? current : [...current, entityId],
    );
  }

  return {
    artifactFilter,
    artifactSort,
    ctaLabel,
    editableHeadline,
    galleryLayout,
    galleryArtifacts,
    galleryQuery,
    groupByAccount,
    focusPane,
    headlineAlign,
    headlineColor,
    headlineFont,
    headlineSize,
    headlineWeight,
    heroImageFit,
    heroImagePath,
    heroImageRadius,
    inspectorOpen,
    inspectorSelection,
    modelPickerOpen,
    openArtifact,
    openGallery,
    openPlan() {
      if (!workspace.plan) return;
      setPreviewSurface("planning");
      setSurface("artifact");
    },
    openQuestionnaire() {
      if (!workspace.questionnaire) return;
      setPreviewSurface("questionnaire");
      setSurface("artifact");
    },
    openHome() {
      router.push("/");
    },
    openTargetAccounts() {
      const targetAccounts = workspace.artifacts.find((artifact) => artifact.type === "table");
      if (targetAccounts) openArtifact(targetAccounts.id);
    },
    previewSurface,
    prompt,
    previewDevice,
    previewZoom,
    questionnaire,
    selectInspector(selection: InspectorSelection) {
      setInspectorSelection(selection);
      setInspectorOpen(true);
    },
    selectedArtifact,
    selectedEntities,
    selectedEntityIds,
    selectedModel,
    selectModel(modelId: string) {
      setSelectedModelId(modelId);
      setModelPickerOpen(false);
    },
    selectEntity,
    setCtaLabel,
    setArtifactFilter,
    setArtifactSort,
    setEditableHeadline,
    setGalleryLayout,
    setGalleryQuery,
    setGroupByAccount,
    setHeadlineAlign,
    setHeadlineColor,
    setHeadlineFont,
    setHeadlineSize,
    setHeadlineWeight,
    setHeroImageFit,
    setHeroImageRadius,
    setInspectorOpen,
    setInspectorSelection,
    setPrompt,
    setPreviewDevice,
    setPreviewZoom,
    setQuestionnaire,
    submitQuestionnaire() {
      // The questionnaire is an artifact-side preview screen with no backend of
      // its own; submitting closes it. It no longer jumps a conversation state,
      // because the conversation is real now and only a turn can move it.
      setPreviewSurface("conversation");
      setSurface("gallery");
    },
    surface,
    replaceHeroImage(file: File) {
      if (heroImageObjectUrl.current) URL.revokeObjectURL(heroImageObjectUrl.current);
      const objectUrl = URL.createObjectURL(file);
      heroImageObjectUrl.current = objectUrl;
      setHeroImagePath(objectUrl);
    },
    toggleArtifactFocus() {
      setFocusPane((current) => current === "artifacts" ? "split" : "artifacts");
    },
    toggleConversationFocus() {
      setFocusPane((current) => current === "conversation" ? "split" : "conversation");
    },
    cyclePreviewDevice() {
      setPreviewDevice((current) => current === "desktop" ? "tablet" : current === "tablet" ? "mobile" : "desktop");
    },
    toggleModelPicker() {
      setModelPickerOpen((current) => !current);
    },
    removeEntity(entityId: string) {
      setSelectedEntityIds((current) => current.filter((id) => id !== entityId));
    },
  };
}
