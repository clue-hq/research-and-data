import type { ProjectWorkspace } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

export function ProjectPlan({ plan }: { plan: ProjectWorkspace["plan"] }) {
  return (
    <section className={styles.projectPlan}>
      <header><span><ProjectIcon name="file-text" size={12} />Plan</span></header>
      <div className={styles.planScroll}>
        <article>
          <h1>{plan.title}</h1>
          <p><strong>Target audience:</strong> {plan.audience}</p>
          <h2>Structure</h2>
          {plan.sections.map((section) => (
            <section key={section.title}>
              <h3>{section.title}</h3>
              <ul>
                {section.lines.map((line) => <li key={line}>{line}</li>)}
              </ul>
            </section>
          ))}
        </article>
      </div>
    </section>
  );
}
