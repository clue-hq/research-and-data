import type { ProjectHome } from "../model/project-workspace";
import { ProjectComposer } from "./project-composer";
import styles from "./project-flow.module.css";

export function ProjectHomeView({
  controller,
  data,
}: {
  controller: ReturnType<typeof import("../hooks/use-project-home-controller").useProjectHomeController>;
  data: ProjectHome;
}) {
  return (
    <main className={styles.home}>
      <section className={styles.homeHero}>
        <div className={styles.homeComposer}>
          <h1>What will you create today?</h1>
          <ProjectComposer
            attachments={controller.attachments}
            entities={data.entities}
            modelPickerOpen={controller.modelPickerOpen}
            models={data.models}
            onAttachmentFiles={controller.addAttachments}
            onAttachmentRemove={controller.removeAttachment}
            onEntityRemove={controller.removeEntity}
            onEntitySelect={controller.selectEntity}
            onModelPickerToggle={controller.toggleModelPicker}
            onModelSelect={controller.selectModel}
            onPromptChange={controller.setPrompt}
            onSubmit={controller.submit}
            prompt={controller.prompt}
            selectedEntities={controller.selectedEntities}
            selectedEntityIds={controller.selectedEntityIds}
            selectedModel={controller.selectedModel}
          />
          <div className={styles.homeSuggestions}>
            {controller.suggestions.map((suggestion, index) => (
              <button
                key={`${index}-${suggestion}`}
                onClick={() => controller.setPrompt(suggestion)}
                title={suggestion}
                type="button"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
