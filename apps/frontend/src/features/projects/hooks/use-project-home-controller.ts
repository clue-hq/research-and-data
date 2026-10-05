import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ClueChatApiError,
  newIdempotencyKey,
} from "../data/chat-api";
import { useChatRepositories } from "../data/projects-transport";
import {
  HomeSubmissionCoordinator,
  parseHomeBootstrapDraft,
} from "../model/home-submission";
import type {
  ProjectEntity,
  ProjectHome,
} from "../model/project-workspace";
import { useChatAttachments } from "./use-chat-attachments";
import { useMentionDirectory } from "./use-mention-directory";

export function useProjectHomeController(data: ProjectHome) {
  const router = useRouter();
  const repositories = useChatRepositories();
  const httpMode = repositories.transport.mode === "http";
  const [home, setHome] = useState(data);
  // The @ tagger's accounts and contacts: the whole workspace directory once loaded.
  const mention = useMentionDirectory(null, home.entities);
  const [prompt, setPromptState] = useState("");
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [selectedEntityIds, setSelectedEntityIds] = useState<string[]>([]);
  const [selectedBrandId, setSelectedBrandIdState] = useState(
    data.defaultBrandId ?? data.brands[0]?.id ?? "",
  );
  const [selectedModelId, setSelectedModelId] = useState(
    data.defaultAgentProfileId ?? data.models[0]?.id ?? "",
  );
  const [loading, setLoading] = useState(httpMode);
  const [inFlightFingerprints, setInFlightFingerprints] = useState<
    ReadonlySet<string>
  >(new Set());
  const [error, setError] = useState<string | null>(null);
  // Real uploads, and only where one can land: the fixture transport has no
  // upload endpoint, so the fixture Home carries no attachments at all rather
  // than a simulated receipt that no submission could cite.
  const attachmentsEnabled = httpMode && home.composerCapabilities.attachments;
  const chatAttachments = useChatAttachments({ enabled: attachmentsEnabled });
  const mounted = useRef(true);
  const draft = useRef({
    agentProfileId:
      data.defaultAgentProfileId ?? data.models[0]?.id ?? null,
    attachmentRefs: [],
    brandId: data.defaultBrandId ?? data.brands[0]?.id ?? "",
    contextRefs: [] as {
      objectId: string;
      objectType: ProjectEntity["type"];
      version: number | null;
    }[],
    message: "",
  });
  const submissions = useRef(new HomeSubmissionCoordinator());

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!httpMode) return;
    let cancelled = false;
    void repositories.home
      .get()
      .then((next) => {
        if (cancelled) return;
        setHome(next);
        const nextBrandId =
          next.defaultBrandId ?? (next.brands.length === 1 ? next.brands[0].id : "");
        const nextAgentProfileId =
          next.defaultAgentProfileId ?? next.models[0]?.id ?? null;
        draft.current = {
          ...draft.current,
          agentProfileId: nextAgentProfileId,
          brandId: nextBrandId,
          contextRefs: [],
        };
        submissions.current.draftChanged();
        setSelectedBrandIdState(nextBrandId);
        setSelectedEntityIds([]);
        setSelectedModelId(nextAgentProfileId ?? "");
        setError(null);
      })
      .catch((failure: unknown) => {
        if (cancelled) return;
        setError(
          failure instanceof Error
            ? failure.message
            : "Unable to load the Home composer.",
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [httpMode, repositories]);

  const selectedEntities = useMemo(
    () =>
      selectedEntityIds
        .map((id) => mention.entities.find((entity) => entity.id === id))
        .filter((entity): entity is ProjectEntity => Boolean(entity)),
    [mention.entities, selectedEntityIds],
  );

  const selectedModel =
    home.models.find((model) => model.id === selectedModelId) ?? home.models[0];

  const contextRefs = selectedEntities.map((entity) => ({
    objectId: entity.id,
    objectType: entity.type,
    version: null,
  }));

  const currentDraft = parseHomeBootstrapDraft({
    agentProfileId: selectedModel?.id ?? null,
    // The refs are part of the draft's identity, so the in-flight fingerprint
    // this reads is the same one `submit` below registers.
    attachmentRefs: [...(chatAttachments.snapshot() ?? [])],
    brandId: selectedBrandId,
    contextRefs,
    message: prompt,
  });
  const submitting = currentDraft.success
    ? inFlightFingerprints.has(currentDraft.fingerprint)
    : false;

  function reviseDraft(next: typeof draft.current) {
    if (JSON.stringify(draft.current) === JSON.stringify(next)) return;
    draft.current = next;
    submissions.current.draftChanged();
    setError(null);
  }

  function setPrompt(value: string) {
    reviseDraft({ ...draft.current, message: value });
    setPromptState(value);
  }

  function setSelectedBrandId(value: string) {
    reviseDraft({ ...draft.current, brandId: value });
    setSelectedBrandIdState(value);
  }

  function selectEntity(entityId: string) {
    setSelectedEntityIds((current) => {
      const next = current.includes(entityId) ? current : [...current, entityId];
      reviseDraft({
        ...draft.current,
        contextRefs: next
          .map((id) => mention.entities.find((entity) => entity.id === id))
          .filter((entity): entity is ProjectEntity => Boolean(entity))
          .map((entity) => ({
            objectId: entity.id,
            objectType: entity.type,
            version: null,
          })),
      });
      return next;
    });
  }

  function removeEntity(entityId: string) {
    setSelectedEntityIds((current) => {
      const next = current.filter((id) => id !== entityId);
      reviseDraft({
        ...draft.current,
        contextRefs: next
          .map((id) => mention.entities.find((entity) => entity.id === id))
          .filter((entity): entity is ProjectEntity => Boolean(entity))
          .map((entity) => ({
            objectId: entity.id,
            objectType: entity.type,
            version: null,
          })),
      });
      return next;
    });
  }

  async function submit(promptOverride?: string, entityIdsOverride?: string[]) {
    const message = promptOverride ?? prompt;
    if (loading) return false;
    // Snapshot before anything else: the project this starts carries the files
    // that had finished uploading when the user pressed send, and a submission
    // that would drop one still in flight is refused instead.
    const attachmentSnapshot = chatAttachments.snapshot();
    if (chatAttachments.attachments.length > 0 && attachmentSnapshot === null) {
      setError("Wait for attachments to finish uploading.");
      return false;
    }
    const submittedEntities = (entityIdsOverride ?? selectedEntityIds)
      .map((id) => mention.entities.find((entity) => entity.id === id))
      .filter((entity): entity is ProjectEntity => Boolean(entity));
    const parsed = parseHomeBootstrapDraft({
      agentProfileId: selectedModel?.id ?? null,
      attachmentRefs: [...(attachmentSnapshot ?? [])],
      brandId: selectedBrandId,
      contextRefs: submittedEntities.map((entity) => ({
        objectId: entity.id,
        objectType: entity.type,
        version: null,
      })),
      message,
    });
    if (!parsed.success) {
      setError(parsed.message);
      return false;
    }
    const attempt = submissions.current.begin(
      parsed.fingerprint,
      () => newIdempotencyKey("home-project"),
    );
    if (!attempt) return false;
    setInFlightFingerprints((current) =>
      new Set(current).add(parsed.fingerprint),
    );
    setError(null);
    try {
      const created = await repositories.home.create({
        ...parsed.request,
        idempotencyKey: attempt.idempotencyKey,
      });
      const outcome = submissions.current.succeeded(attempt);
      if (!mounted.current) return true;
      // The attachments live in their own hook, not in `draft.current`, so the
      // comparison reads them where they are: a draft is still "the one that
      // was sent" only if its files are also still the sent ones.
      const latestDraft = parseHomeBootstrapDraft({
        ...draft.current,
        attachmentRefs: [...(chatAttachments.snapshot() ?? [])],
      });
      if (latestDraft.success && latestDraft.fingerprint === parsed.fingerprint) {
        draft.current = { ...draft.current, contextRefs: [], message: "" };
        submissions.current.draftChanged();
        setPromptState("");
        setSelectedEntityIds([]);
        chatAttachments.clear();
      }
      if (outcome.navigate) router.push(created.href);
      return true;
    } catch (failure) {
      const outcome = submissions.current.failed(attempt);
      if (!mounted.current || !outcome.display) return false;
      if (failure instanceof ClueChatApiError) {
        setError(
          failure.requestId
            ? `${failure.message} (request ${failure.requestId})`
            : failure.message,
        );
      } else {
        setError(failure instanceof Error ? failure.message : String(failure));
      }
      return false;
    } finally {
      if (mounted.current) {
        setInFlightFingerprints((current) => {
          const next = new Set(current);
          next.delete(parsed.fingerprint);
          return next;
        });
      }
    }
  }

  return {
    // Withheld where no upload can land, so the composer hides the `+` button
    // rather than offering one whose files would go nowhere.
    addAttachments: attachmentsEnabled ? chatAttachments.onFiles : undefined,
    // The hook's own refusals (an unsupported file, a failed upload) render
    // inside the composer; `error` stays the submission's surface.
    attachmentError: chatAttachments.error,
    attachments: [...chatAttachments.attachments],
    data: home,
    error,
    loading,
    // The @ tagger's accounts and contacts: the whole workspace directory.
    mentionEntities: mention.entities,
    modelPickerOpen,
    onMentionQueryChange: mention.onMentionQueryChange,
    prompt,
    removeAttachment: attachmentsEnabled ? chatAttachments.remove : undefined,
    removeEntity,
    selectEntity,
    selectModel(modelId: string) {
      reviseDraft({ ...draft.current, agentProfileId: modelId });
      setSelectedModelId(modelId);
      setModelPickerOpen(false);
    },
    selectedEntities,
    selectedEntityIds,
    selectedBrandId,
    selectedModel,
    setSelectedBrandId,
    setPrompt,
    submit,
    submitting,
    toggleModelPicker() {
      setModelPickerOpen((current) => !current);
    },
    suggestions: home.suggestions,
  };
}
