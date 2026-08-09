import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ClueChatApiError,
  newIdempotencyKey,
} from "../data/chat-api";
import { useChatRepositories } from "../data/projects-transport";
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
  const [selectedBrandId, setSelectedBrandId] = useState(
    data.defaultBrandId ?? data.brands[0]?.id ?? "",
  );
  const [selectedModelId, setSelectedModelId] = useState(data.models[0]?.id ?? "");
  const [loading, setLoading] = useState(httpMode);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const attachmentUrls = useRef(new Set<string>());
  const uploadTimers = useRef<number[]>([]);
  const pendingSubmission = useRef<{
    fingerprint: string;
    idempotencyKey: string;
  } | null>(null);

  useEffect(() => () => {
    uploadTimers.current.forEach((timer) => window.clearTimeout(timer));
    attachmentUrls.current.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  useEffect(() => {
    if (!httpMode) return;
    let cancelled = false;
    void repositories.home
      .get()
      .then((next) => {
        if (cancelled) return;
        setHome(next);
        setSelectedBrandId(
          next.defaultBrandId ?? (next.brands.length === 1 ? next.brands[0].id : ""),
        );
        setSelectedModelId(next.models[0]?.id ?? "");
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

  function setPrompt(value: string) {
    setPromptState(value);
  }

  function selectEntity(entityId: string) {
    setSelectedEntityIds((current) =>
      current.includes(entityId) ? current : [...current, entityId],
    );
  }

  function removeEntity(entityId: string) {
    setSelectedEntityIds((current) => current.filter((id) => id !== entityId));
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

  async function submit(promptOverride?: string) {
    const message = promptOverride ?? prompt;
    if (!message.trim() || !selectedBrandId || loading || submitting) return;
    const fingerprint = JSON.stringify({ brandId: selectedBrandId, message });
    const attempt = pendingSubmission.current;
    const idempotencyKey =
      attempt?.fingerprint === fingerprint
        ? attempt.idempotencyKey
        : newIdempotencyKey("home-project");
    pendingSubmission.current = { fingerprint, idempotencyKey };
    setSubmitting(true);
    setError(null);
    try {
      const created = await repositories.home.create({
        brandId: selectedBrandId,
        message,
        idempotencyKey,
      });
      pendingSubmission.current = null;
      router.push(created.href);
    } catch (failure) {
      if (failure instanceof ClueChatApiError) {
        setError(
          failure.requestId
            ? `${failure.message} (request ${failure.requestId})`
            : failure.message,
        );
      } else {
        setError(failure instanceof Error ? failure.message : String(failure));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return {
    addAttachments,
    attachments,
    data: home,
    error,
    loading,
    modelPickerOpen,
    prompt,
    removeAttachment(attachmentId: string) {
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
