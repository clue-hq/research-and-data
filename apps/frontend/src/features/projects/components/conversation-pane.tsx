import type { ProjectWorkspace } from "../model/project-workspace";
import { useTranscriptAutoScroll } from "../hooks/use-transcript-auto-scroll";
import { CanvasInspector } from "./canvas-inspector";
import { ProjectComposer } from "./project-composer";
import { ProjectIcon } from "./project-icon";
import { PlanApproval } from "./plan-approval";
import { ProjectMessageTimeline } from "./project-message-timeline";
import styles from "./project-flow.module.css";

export function ConversationPane({
  controller,
  workspace,
}: {
  controller: ReturnType<typeof import("../hooks/use-project-workspace-controller").useProjectWorkspaceController>;
  workspace: ProjectWorkspace;
}) {
  const { transcriptScrollRef } = useTranscriptAutoScroll({
    generationProgress: controller.generationProgress,
    phase: controller.phase,
  });

  if (controller.inspectorOpen) {
    return (
      <section className={styles.conversationPane} data-mode="inspector">
        <header className={styles.conversationHeader}>
          <strong>{controller.activeThread.title}</strong>
          <div><button aria-label="New thread" onClick={controller.createThread} type="button"><ProjectIcon name="plus" size={14} /></button><button aria-label="Close inspector" className={styles.activeTool} onClick={() => controller.setInspectorOpen(false)} type="button"><ProjectIcon name="edit-active" size={14} /></button><button aria-label="Expand conversation" aria-pressed={controller.focusPane === "conversation"} onClick={controller.toggleConversationFocus} type="button"><ProjectIcon name="expand" size={14} /></button></div>
        </header>
        <CanvasInspector
          ctaLabel={controller.ctaLabel}
          headlineAlign={controller.headlineAlign}
          headlineFont={controller.headlineFont}
          headlineSize={controller.headlineSize / 2}
          headlineWeight={controller.headlineWeight}
          heroImageFit={controller.heroImageFit}
          heroImageRadius={controller.heroImageRadius}
          onCtaLabelChange={controller.setCtaLabel}
          onHeadlineAlignChange={controller.setHeadlineAlign}
          onHeadlineColorChange={controller.setHeadlineColor}
          onHeadlineFontChange={controller.setHeadlineFont}
          onHeadlineSizeChange={(size) => controller.setHeadlineSize(size * 2)}
          onHeadlineWeightChange={controller.setHeadlineWeight}
          onHeroImageFitChange={controller.setHeroImageFit}
          onHeroImageRadiusChange={controller.setHeroImageRadius}
          onHeroImageReplace={controller.replaceHeroImage}
          selection={controller.inspectorSelection}
        />
        <div className={styles.inspectorComposer}>
          <span className={styles.selectionTag}>heading 1 <button onClick={() => controller.setInspectorSelection("canvas")} type="button">×</button></span>
          <ProjectComposer
            entities={workspace.contextEntities}
            modelPickerOpen={controller.modelPickerOpen}
            models={workspace.models}
            onEntityRemove={controller.removeEntity}
            onEntitySelect={controller.selectEntity}
            onModelPickerToggle={controller.toggleModelPicker}
            onModelSelect={controller.selectModel}
            onPromptChange={controller.setPrompt}
            onSubmit={controller.submitMessage}
            prompt={controller.prompt}
            selectedEntities={controller.selectedEntities}
            selectedEntityIds={controller.selectedEntityIds}
            selectedModel={controller.selectedModel}
          />
        </div>
      </section>
    );
  }

  return (
    <section className={styles.conversationPane}>
      <header className={styles.conversationHeader}>
        <label>
          <select onChange={(event) => controller.selectThread(event.target.value)} value={controller.activeThread.id}>
            {controller.threads.map((thread) => <option key={thread.id} value={thread.id}>{thread.title}</option>)}
          </select>
          <ProjectIcon name="chevron-down" size={12} />
        </label>
        <div><button aria-label="New thread" onClick={controller.createThread} type="button"><ProjectIcon name="plus" size={14} /></button><button aria-label="Open canvas inspector" onClick={() => controller.setInspectorOpen(true)} type="button"><ProjectIcon name="edit" size={14} /></button><button aria-label="Expand conversation" aria-pressed={controller.focusPane === "conversation"} onClick={controller.toggleConversationFocus} type="button"><ProjectIcon name="expand" size={14} /></button></div>
      </header>
      <div className={styles.transcriptScroll} ref={transcriptScrollRef}>
        <ProjectMessageTimeline
          controller={controller}
          messages={controller.messages}
          workspace={workspace}
        />
      </div>
      <div className={styles.workspaceComposer} data-phase={controller.phase}>
        {controller.phase === "planning" ? (
          <PlanApproval
            label={workspace.conversationCopy.planCardLabel}
            onAccept={controller.acceptPlan}
            onReject={controller.rejectPlan}
            onRevise={controller.revisePlan}
          />
        ) : null}
        <ProjectComposer
          disabled={controller.phase === "generating"}
          entities={workspace.contextEntities}
          modelPickerOpen={controller.modelPickerOpen}
          models={workspace.models}
          onEntityRemove={controller.removeEntity}
          onEntitySelect={controller.selectEntity}
          onModelPickerToggle={controller.toggleModelPicker}
          onModelSelect={controller.selectModel}
          onPromptChange={controller.setPrompt}
          onSubmit={controller.submitMessage}
          prompt={controller.prompt}
          selectedEntities={controller.selectedEntities}
          selectedEntityIds={controller.selectedEntityIds}
          selectedModel={controller.selectedModel}
        />
      </div>
    </section>
  );
}
