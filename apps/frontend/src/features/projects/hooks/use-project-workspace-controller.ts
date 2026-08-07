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
  ProjectThread,
  ProjectWorkspace,
} from "../model/project-workspace";
import { buildProjectMessages } from "../data/build-project-messages";

export interface ProjectWorkspaceInitialState {
  artifactId?: string;
  entityIds?: string[];
  modelId?: string;
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
  const timers = useRef<Array<ReturnType<typeof setTimeout>>>([]);
  const [phase, setPhase] = useState(initial.phase);
  const [surface, setSurface] = useState(initial.surface);
  const [prompt, setPromptState] = useState("");
  const [activeThreadId, setActiveThreadId] = useState(
    initial.threadId ?? workspace.threads[0].id,
  );
  const [threads, setThreads] = useState<ProjectThread[]>(workspace.threads);
  const [selectedModelId, setSelectedModelId] = useState(
    initial.modelId && workspace.models.some((model) => model.id === initial.modelId)
      ? initial.modelId
      : workspace.defaultModelId,
  );
  const [selectedArtifactId, setSelectedArtifactId] = useState(
    initial.artifactId ?? workspace.artifacts[2]?.id ?? workspace.artifacts[0].id,
  );
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [selectedEntityIds, setSelectedEntityIds] = useState(() =>
    (initial.entityIds ?? []).filter((id) =>
      workspace.contextEntities.some((entity) => entity.id === id),
    ),
  );
  const [chainOpen, setChainOpen] = useState(true);
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
  const [generationProgress, setGenerationProgress] = useState(
    initial.phase === "generating" ? workspace.previewTimeline.generationStartProgress : 0,
  );
  const [generationDetailsOpen, setGenerationDetailsOpen] = useState(true);
  const [questionnaire, setQuestionnaire] = useState({
    primaryActionId: workspace.questionnaire.primaryAction.defaultChoiceId,
    secondaryActionId: workspace.questionnaire.secondaryAction.defaultChoiceId,
    targetAccounts: workspace.questionnaire.targetAccounts.defaultValue,
    themeId: workspace.questionnaire.theme.defaultChoiceId,
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
  const activeThread = useMemo(
    () =>
      threads.find((thread) => thread.id === activeThreadId) ?? threads[0],
    [activeThreadId, threads],
  );
  const galleryArtifacts = useMemo(() => {
    const phaseArtifacts = phase === "complete"
      ? workspace.artifacts
      : phase === "generating"
        ? workspace.artifacts.slice(0, 1)
        : [];
    const query = galleryQuery.trim().toLocaleLowerCase();
    const filtered = phaseArtifacts.filter((artifact) => {
      if (artifactFilter !== "all" && artifact.type !== artifactFilter) return false;
      if (!query) return true;
      return `${artifact.title} ${artifact.editedLabel}`.toLocaleLowerCase().includes(query);
    });
    return artifactSort === "name"
      ? [...filtered].sort((left, right) => left.title.localeCompare(right.title))
      : filtered;
  }, [artifactFilter, artifactSort, galleryQuery, phase, workspace.artifacts]);
  const messages = useMemo(
    () => buildProjectMessages({ generationProgress, phase, workspace }),
    [generationProgress, phase, workspace],
  );

  useEffect(() => {
    const activeTimers = timers.current;
    return () => {
      activeTimers.forEach((timer) => clearTimeout(timer));
      if (heroImageObjectUrl.current) URL.revokeObjectURL(heroImageObjectUrl.current);
    };
  }, []);

  useEffect(() => {
    if (initial.phase !== "conversation") return;
    const timer = setTimeout(() => {
      setPhase("questionnaire");
      setSurface("artifact");
    }, workspace.previewTimeline.conversationToQuestionnaireMs);
    timers.current.push(timer);
    return () => clearTimeout(timer);
  }, [initial.phase, workspace.previewTimeline.conversationToQuestionnaireMs]);

  useEffect(() => {
    if (phase !== "agent-running") return;
    const timer = setTimeout(
      () => setPhase("planning"),
      workspace.previewTimeline.agentRunningMs,
    );
    timers.current.push(timer);
    return () => clearTimeout(timer);
  }, [phase, workspace.previewTimeline.agentRunningMs]);

  useEffect(() => {
    if (phase !== "generating") return;
    workspace.previewTimeline.generationMilestones.forEach(({ delayMs, progress }) => {
      const timer = setTimeout(() => {
        setGenerationProgress(progress);
        if (progress === 100) {
          setPhase("complete");
          setSurface("gallery");
        }
      }, delayMs);
      timers.current.push(timer);
    });
  }, [phase, workspace.previewTimeline.generationMilestones]);

  function syncRoute(artifactId?: string, threadId = activeThreadId) {
    const params = new URLSearchParams({ thread: threadId });
    const suffix = `?${params.toString()}`;
    if (artifactId) {
      router.replace(`/projects/${workspace.id}/artifacts/${artifactId}${suffix}`, {
        scroll: false,
      });
      return;
    }
    router.replace(`/projects/${workspace.id}/gallery${suffix}`, { scroll: false });
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
    setInspectorOpen(false);
    syncRoute();
  }

  function selectThread(threadId: string) {
    setActiveThreadId(threadId);
    const url = new URL(window.location.href);
    url.searchParams.set("thread", threadId);
    window.history.pushState(null, "", `${url.pathname}?${url.searchParams.toString()}`);
  }

  function createThread() {
    const id = `thread-local-${threads.length + 1}`;
    const thread = { id, title: `New chat ${threads.length + 1}` };
    setThreads((current) => [...current, thread]);
    setActiveThreadId(id);
    setPromptState("");
    setPhase("conversation");
    setSurface("gallery");
    const url = new URL(window.location.href);
    url.searchParams.set("thread", id);
    window.history.pushState(null, "", `/projects/${workspace.id}/gallery?${url.searchParams.toString()}`);
  }

  function submitMessage(promptOverride?: string, entityIdsOverride?: string[]) {
    if (!(promptOverride ?? prompt).trim()) return;
    if (entityIdsOverride) setSelectedEntityIds(entityIdsOverride);
    setPromptState("");
    setPhase("planning");
    setSurface("gallery");
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
    acceptPlan() {
      setGenerationProgress(workspace.previewTimeline.generationStartProgress);
      setPhase("generating");
      setSurface("gallery");
    },
    activeThread,
    artifactFilter,
    artifactSort,
    chainOpen,
    createThread,
    ctaLabel,
    editableHeadline,
    galleryLayout,
    galleryArtifacts,
    galleryQuery,
    generationDetailsOpen,
    generationProgress,
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
    messages,
    openArtifact,
    openGallery,
    openPlan() {
      setPhase("planning");
      setSurface("artifact");
    },
    openQuestionnaire() {
      setPhase("questionnaire");
      setSurface("artifact");
    },
    openHome() {
      router.push("/");
    },
    openTargetAccounts() {
      const targetAccounts = workspace.artifacts.find((artifact) => artifact.type === "table");
      if (targetAccounts) openArtifact(targetAccounts.id);
    },
    phase,
    prompt,
    previewDevice,
    previewZoom,
    questionnaire,
    rejectPlan() {
      setPhase("questionnaire");
      setSurface("artifact");
    },
    revisePlan() {
      setPromptState("Revise the plan: ");
    },
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
    selectThread,
    setChainOpen,
    setCtaLabel,
    setArtifactFilter,
    setArtifactSort,
    setEditableHeadline,
    setGalleryLayout,
    setGalleryQuery,
    setGenerationDetailsOpen,
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
    submitMessage,
    submitQuestionnaire() {
      setPhase("agent-running");
      setSurface("gallery");
    },
    surface,
    threads,
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
