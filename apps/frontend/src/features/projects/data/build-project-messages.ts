import type {
  ProjectMessage,
  ProjectPhase,
  ProjectWorkspace,
} from "../model/project-workspace";

interface BuildProjectMessagesInput {
  generationProgress: number;
  phase: ProjectPhase;
  workspace: ProjectWorkspace;
}

const phaseOrder: ProjectPhase[] = [
  "conversation",
  "questionnaire",
  "agent-running",
  "planning",
  "generating",
  "complete",
];

function reached(current: ProjectPhase, target: ProjectPhase) {
  return phaseOrder.indexOf(current) >= phaseOrder.indexOf(target);
}

export function buildProjectMessages({
  generationProgress,
  phase,
  workspace,
}: BuildProjectMessagesInput): ProjectMessage[] {
  const copy = workspace.conversationCopy;
  const messages: ProjectMessage[] = [
    {
      id: "initial-request",
      parts: [{ id: "initial-request-text", text: workspace.prompt, type: "text" }],
      role: "user",
    },
  ];

  if (phase === "conversation") {
    messages.push({
      id: "initial-reasoning",
      parts: [{
        detail: copy.initialReasoning,
        id: "initial-reasoning-part",
        label: "Thinking",
        showTrace: false,
        streaming: true,
        type: "reasoning",
      }],
      role: "assistant",
    });
    return messages;
  }

  if (reached(phase, "questionnaire")) {
    messages.push({
      authorLabel: copy.assistantName,
      id: "questionnaire-request",
      parts: [
        {
          id: "questionnaire-reasoning",
          label: copy.reasoningLabel,
          showTrace: false,
          streaming: false,
          type: "reasoning",
        },
        ...copy.beforeQuestionnaire.map((text, index) => ({
          id: `questionnaire-copy-${index + 1}`,
          text,
          type: "text" as const,
        })),
        {
          action: "questionnaire" as const,
          icon: "clipboard-list" as const,
          id: "questionnaire-action",
          label: copy.questionnaireCardLabel,
          type: "action" as const,
        },
      ],
      role: "assistant",
    });
  }

  if (reached(phase, "agent-running")) {
    const planningParts: ProjectMessage["parts"] = [
      { id: "plan-starting-copy", text: copy.planStarting, type: "text" },
    ];

    if (phase === "agent-running") {
      planningParts.push({
        id: "agent-running-reasoning",
        label: copy.agentRunningLabel,
        showTrace: false,
        streaming: true,
        type: "reasoning",
      });
    } else {
      const [accountTool, researchTool] = workspace.conversationActivity.tools;
      planningParts.push(
        {
          id: "completed-reasoning",
          label: copy.reasoningLabel,
          showTrace: true,
          streaming: false,
          type: "reasoning",
        },
        {
          id: accountTool.id,
          input: accountTool.input,
          output: accountTool.output,
          state: "output-available",
          title: accountTool.title,
          type: "tool",
        },
        {
          id: researchTool.id,
          input: researchTool.input,
          output: researchTool.output,
          state: "output-available",
          title: researchTool.title,
          type: "tool",
        },
        { id: "plan-created-copy", text: copy.planCreated, type: "text" },
        { id: "plan-summary", type: "plan" },
      );
    }

    messages.push({
      id: "planning-work",
      parts: planningParts,
      role: "assistant",
    });
  }

  if (phase === "generating" || phase === "complete") {
    messages.push({
      authorLabel: copy.assistantName,
      id: "generation-work",
      parts: [
        { id: "generation-accepted", text: copy.buildingAccepted, type: "text" },
        {
          complete: phase === "complete",
          id: "generation-task",
          progress: generationProgress,
          type: "task",
        },
        ...(phase === "complete"
          ? [{ id: "generation-sources", type: "sources" as const }]
          : []),
      ],
      role: "assistant",
    });
  }

  return messages;
}
