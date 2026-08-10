import type { ProjectQuestionGroup, ProjectQuestionnaire as ProjectQuestionnaireData } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

export interface ProjectQuestionnaireValue {
  primaryActionId: string;
  secondaryActionId: string;
  targetAccounts: string;
  themeId: string;
}

function ChoiceGroup({
  group,
  onChange,
  value,
}: {
  group: ProjectQuestionGroup;
  onChange: (choiceId: string) => void;
  value: string;
}) {
  return (
    <fieldset className={styles.questionChoiceGroup}>
      <legend>{group.question}</legend>
      <p>{group.hint}</p>
      <div>
        {group.options.map((option) => (
          <button
            aria-pressed={value === option.id}
            key={option.id}
            onClick={() => onChange(option.id)}
            type="button"
          >
            {option.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

export function ProjectQuestionnaire({
  data,
  onChange,
  onSubmit,
  value,
}: {
  data: ProjectQuestionnaireData;
  onChange: (value: ProjectQuestionnaireValue) => void;
  onSubmit: () => void;
  value: ProjectQuestionnaireValue;
}) {
  return (
    <section className={styles.questionnaire}>
      <header className={styles.questionnaireToolbar}>
        <span><ProjectIcon name="clipboard-list" size={12} />Questionnaire</span>
        <button onClick={onSubmit} type="button">Submit</button>
      </header>
      <div className={styles.questionnaireScroll}>
        <form onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
          <h2>{data.title}</h2>
          <hr />
          <label className={styles.targetAccountQuestion}>
            <strong>{data.targetAccounts.question}</strong>
            <span>{data.targetAccounts.hint}</span>
            <textarea
              onChange={(event) => onChange({ ...value, targetAccounts: event.target.value })}
              value={value.targetAccounts}
            />
          </label>
          <hr />
          <ChoiceGroup
            group={data.primaryAction}
            onChange={(primaryActionId) => onChange({ ...value, primaryActionId })}
            value={value.primaryActionId}
          />
          <hr />
          <ChoiceGroup
            group={data.secondaryAction}
            onChange={(secondaryActionId) => onChange({ ...value, secondaryActionId })}
            value={value.secondaryActionId}
          />
          <hr />
          <ChoiceGroup
            group={data.theme}
            onChange={(themeId) => onChange({ ...value, themeId })}
            value={value.themeId}
          />
        </form>
      </div>
    </section>
  );
}
