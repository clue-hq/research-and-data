import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
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
  const [prompt, setPromptState] = useState("");
  const [attachments, setAttachments] = useState<ProjectComposerAttachment[]>([]);
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [selectedEntityIds, setSelectedEntityIds] = useState<string[]>([]);
  const [selectedModelId, setSelectedModelId] = useState(data.models[0].id);
  const attachmentUrls = useRef(new Set<string>());
  const uploadTimers = useRef<number[]>([]);

  useEffect(() => () => {
    uploadTimers.current.forEach((timer) => window.clearTimeout(timer));
    attachmentUrls.current.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  const selectedEntities = useMemo(
    () =>
      selectedEntityIds
        .map((id) => data.entities.find((entity) => entity.id === id))
        .filter((entity): entity is ProjectEntity => Boolean(entity)),
    [data.entities, selectedEntityIds],
  );

  const suggestions = useMemo(() => {
    if (prompt.trim().length <= 1) return data.suggestions;
    return data.suggestions.map((suggestion, index) => index === 1 ? prompt.trim() : suggestion);
  }, [data.suggestions, prompt]);

  const selectedModel =
    data.models.find((model) => model.id === selectedModelId) ?? data.models[0];

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

  function submit(promptOverride?: string, entityIdsOverride?: string[]) {
    const normalizedPrompt = (promptOverride ?? prompt).trim() || "design a landing page";
    const contextEntityIds = entityIdsOverride ?? selectedEntityIds;
    const query = new URLSearchParams({
      model: selectedModel.id,
      phase: "conversation",
      prompt: normalizedPrompt,
      thread: data.suggestedThreadId,
    });
    if (contextEntityIds.length) {
      query.set("entities", contextEntityIds.join(","));
    }
    router.push(`/projects/${data.suggestedProjectId}?${query.toString()}`);
  }

  return {
    addAttachments,
    attachments,
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
    selectedModel,
    setPrompt,
    submit,
    toggleModelPicker() {
      setModelPickerOpen((current) => !current);
    },
    suggestions,
  };
}
