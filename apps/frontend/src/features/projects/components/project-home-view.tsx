import { ProjectComposer } from "./project-composer";
import styles from "./project-flow.module.css";

export function ProjectHomeView({
  controller,
}: {
  controller: ReturnType<typeof import("../hooks/use-project-home-controller").useProjectHomeController>;
}) {
  const data = controller.data;
  return (
    <main className={styles.home}>
      <section className={styles.homeHero}>
        <div className={styles.homeComposer}>
          <h1>What will you create today?</h1>
          {data.brands.length > 1 || !controller.selectedBrandId ? (
            <label className={styles.homeBrandPicker}>
              <span>Brand</span>
              <select
                aria-label="Brand"
                disabled={controller.loading}
                onChange={(event) => controller.setSelectedBrandId(event.target.value)}
                value={controller.selectedBrandId}
              >
                <option value="">Select a brand</option>
                {data.brands.map((brand) => (
                  <option key={brand.id} value={brand.id}>
                    {brand.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <ProjectComposer
            attachmentError={controller.attachmentError}
            attachments={controller.attachments}
            entities={controller.mentionEntities}
            onMentionQueryChange={controller.onMentionQueryChange}
            disabled={controller.loading}
            variant="home"
            modelPickerOpen={controller.modelPickerOpen}
            models={data.models}
            onAttachmentFiles={
              data.composerCapabilities.attachments
                ? controller.addAttachments
                : undefined
            }
            onAttachmentRemove={
              data.composerCapabilities.attachments
                ? controller.removeAttachment
                : undefined
            }
            onEntityRemove={
              data.composerCapabilities.contextRefs
                ? controller.removeEntity
                : undefined
            }
            onEntitySelect={
              data.composerCapabilities.contextRefs
                ? controller.selectEntity
                : undefined
            }
            onModelPickerToggle={controller.toggleModelPicker}
            onModelSelect={controller.selectModel}
            onPromptChange={controller.setPrompt}
            onSubmit={controller.submit}
            prompt={controller.prompt}
            sendDisabled={!controller.selectedBrandId || controller.submitting}
            selectedEntities={controller.selectedEntities}
            selectedEntityIds={controller.selectedEntityIds}
            selectedModel={controller.selectedModel}
          />
          {controller.error ? (
            <p className={styles.homeError} role="alert">
              {controller.error}
            </p>
          ) : null}
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
