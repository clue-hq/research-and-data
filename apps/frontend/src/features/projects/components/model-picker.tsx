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
      {models.filter((model) => model.id !== selectedModelId).map((model) => (
        <button
          className={styles.modelOption}
          key={model.id}
          onClick={() => onSelect(model.id)}
          role="menuitem"
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
