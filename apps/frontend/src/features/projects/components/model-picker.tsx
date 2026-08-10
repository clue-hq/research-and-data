import type { ProjectModelOption } from "../model/project-workspace";
import styles from "./project-flow.module.css";

export function ModelPicker({
  models,
  onSelect,
  selectedModelId,
}: {
  models: ProjectModelOption[];
  onSelect: (modelId: string) => void;
  selectedModelId: string;
}) {
  return (
    <div aria-label="Choose a model" className={styles.modelPicker} role="menu">
      {models.map((model) => (
        <button
          aria-checked={model.id === selectedModelId}
          className={styles.modelOption}
          data-selected={model.id === selectedModelId || undefined}
          key={model.id}
          onClick={() => onSelect(model.id)}
          role="menuitemradio"
          type="button"
        >
          <span>
            <strong>{model.label}</strong>
            <small>{model.description}</small>
          </span>
        </button>
      ))}
    </div>
  );
}
