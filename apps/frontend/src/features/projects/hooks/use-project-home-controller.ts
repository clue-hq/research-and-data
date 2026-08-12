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
import type { ProjectComposerAttachment } from "../model/project-composer";
import type {
  ProjectEntity,
  ProjectHome,
} from "../model/project-workspace";

function getMediaType(file: File) {
  if (file.type) return file.type;
  const extension = file.name.split(".").pop()?.toLocaleLowerCase() ?? "";
  const mediaTypes: Record<string, string> = {
    csv: "text/csv",
    doc: "application/msword",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    gif: "image/gif",
    jpeg: "image/jpeg",
    jpg: "image/jpeg",
    pdf: "application/pdf",
    png: "image/png",
    webp: "image/webp",
    xls: "application/vnd.ms-excel",
    xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  };
  return mediaTypes[extension] ?? "application/octet-stream";
}

export function useProjectHomeController(data: ProjectHome) {
  const router = useRouter();
  const repositories = useChatRepositories();
  const httpMode = repositories.transport.mode === "http";
  const [home, setHome] = useState(data);
  const [prompt, setPromptState] = useState("");
  const [attachments, setAttachments] = useState<ProjectComposerAttachment[]>([]);
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
  const attachmentUrls = useRef(new Set<string>());
  const uploadTimers = useRef<number[]>([]);
  const mounted = useRef(true);
  const draft = useRef({
    agentProfileId:
      data.defaultAgentProfileId ?? data.models[0]?.id ?? null,
    attachmentRefs: [],
    brandId: data.defaultBrandId ?? data.brands[0]?.id ?? "",
    contextRefs: [] as {
      objectId: string;
      objectType: "account" | "contact";
      version: number | null;
    }[],
    message: "",
  });
  const submissions = useRef(new HomeSubmissionCoordinator());

  useEffect(() => {
    const timers = uploadTimers.current;
    const urls = attachmentUrls.current;
    mounted.current = true;
    return () => {
      mounted.current = false;
      timers.forEach((timer) => window.clearTimeout(timer));
      urls.forEach((url) => URL.revokeObjectURL(url));
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
        .map((id) => home.entities.find((entity) => entity.id === id))
        .filter((entity): entity is ProjectEntity => Boolean(entity)),
    [home.entities, selectedEntityIds],
  );

  const suggestions = useMemo(() => {
    if (prompt.trim().length <= 1) return home.suggestions;
    return home.suggestions.map((suggestion, index) => index === 1 ? prompt.trim() : suggestion);
  }, [home.suggestions, prompt]);

  const selectedModel =
    home.models.find((model) => model.id === selectedModelId) ?? home.models[0];

  const contextRefs = selectedEntities.map((entity) => ({
    objectId: entity.id,
    objectType: entity.type,
    version: null,
  }));

  const currentDraft = parseHomeBootstrapDraft({
    agentProfileId: selectedModel?.id ?? null,
    attachmentRefs: [],
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
          .map((id) => home.entities.find((entity) => entity.id === id))
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
          .map((id) => home.entities.find((entity) => entity.id === id))
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

  function addAttachments(files: File[]) {
    const incoming = files.map((file, index) => {
      const mediaType = getMediaType(file);
      const url = mediaType.startsWith("image/") ? URL.createObjectURL(file) : "";
      if (url) attachmentUrls.current.add(url);
      return {
        filename: file.name,
        id: `${file.name}-${file.lastModified}-${index}`,
        mediaType,
        status: "uploading" as const,
        type: "file" as const,
        url,
      };
    });
    setAttachments((current) => [...current, ...incoming]);
    incoming.forEach((attachment, index) => {
      const timer = window.setTimeout(() => {
        setAttachments((current) => current.map((item) =>
          item.id === attachment.id ? { ...item, status: "ready" } : item,
        ));
      }, 650 + index * 180);
      uploadTimers.current.push(timer);
    });
  }

  async function submit(promptOverride?: string, entityIdsOverride?: string[]) {
    const message = promptOverride ?? prompt;
    if (loading) return false;
    const submittedEntities = (entityIdsOverride ?? selectedEntityIds)
      .map((id) => home.entities.find((entity) => entity.id === id))
      .filter((entity): entity is ProjectEntity => Boolean(entity));
    const parsed = parseHomeBootstrapDraft({
      agentProfileId: selectedModel?.id ?? null,
      attachmentRefs: [],
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
      if (mounted.current) {
        const latestDraft = parseHomeBootstrapDraft(draft.current);
        if (latestDraft.success && latestDraft.fingerprint === parsed.fingerprint) {
          draft.current = { ...draft.current, contextRefs: [], message: "" };
          submissions.current.draftChanged();
          setPromptState("");
          setSelectedEntityIds([]);
          attachmentUrls.current.forEach((url) => URL.revokeObjectURL(url));
          attachmentUrls.current.clear();
          setAttachments([]);
        }
        if (outcome.navigate) router.push(created.href);
      }
      return true;
    } catch (failure) {
      const outcome = submissions.current.failed(attempt);
      if (mounted.current && outcome.display) {
        if (failure instanceof ClueChatApiError) {
          setError(
            failure.requestId
              ? `${failure.message} (request ${failure.requestId})`
              : failure.message,
          );
        } else {
          setError(failure instanceof Error ? failure.message : String(failure));
        }
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
    // The timer/object-URL preview belongs only to the isolated fixture
    // transport. HTTP mode has no durable upload receipt endpoint, so it may
    // never expose these handlers even if a mismatched server payload claimed
    // attachments were available.
    addAttachments: httpMode ? undefined : addAttachments,
    attachments: httpMode ? [] : attachments,
    data: home,
    error,
    loading,
    modelPickerOpen,
    prompt,
    removeAttachment: httpMode
      ? undefined
      : (attachmentId: string) => {
          setAttachments((current) => {
            const attachment = current.find((item) => item.id === attachmentId);
            if (attachment?.url) {
              URL.revokeObjectURL(attachment.url);
              attachmentUrls.current.delete(attachment.url);
            }
            return current.filter((item) => item.id !== attachmentId);
          });
        },
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
    suggestions,
  };
}
