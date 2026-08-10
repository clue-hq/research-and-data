import {
  fieldKeyNamespace,
  formatFieldKeyLabel,
  formatIsoDate,
  formatJsonScalar,
  formatToken,
  jsonEntries,
} from "../model/formatting";
import type { Freshness, JsonValue } from "../model/vocabulary";
import readability from "./account-readability.module.css";

/**
 * The absence / redaction / opaque-value primitives.
 *
 * The wire distinguishes three answers and so does the UI: a value we hold, a
 * value we do not hold (absent, unmarked), and a value withheld by display
 * governance (absent, marked). Nothing here ever substitutes a placeholder for
 * a missing value.
 */

export function Absent({ label = "Not available" }: { label?: string }) {
  return (
    <span className="text-[var(--clue-content-subtle)]">
      <span aria-hidden="true">—</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

/** A value the backend holds but policy will not display. Different from absent. */
export function Restricted() {
  return (
    <span
      className={`${readability.pillMedium} inline-flex items-center rounded-xl bg-[var(--clue-background-pressed)] px-2 py-1 text-[var(--clue-content-subtle)]`}
      title="Withheld by display policy"
    >
      Withheld
    </span>
  );
}

/** Renders a text value, or an honest absence when there is none. */
export function ValueOrAbsent({
  label,
  value,
}: {
  label?: string;
  value: string | null | undefined;
}) {
  return value ? <>{value}</> : <Absent label={label} />;
}

/**
 * Renders an opaque claim payload.
 *
 * Scalars render inline; arrays render as chips; objects render as prettified
 * key/value lines. The writer's snake_case keys are surfaced through the same
 * generic prettifier used for field keys, so a payload shape nobody enumerated
 * still reads as a sentence rather than as JSON.
 */
export function FactValue({ value }: { value: JsonValue }) {
  const scalar = formatJsonScalar(value);
  if (scalar !== null) return <>{scalar}</>;
  if (value === null) return <Absent />;

  if (Array.isArray(value)) {
    if (!value.length) return <Absent />;
    return (
      <span className="flex flex-wrap items-center gap-1.5">
        {value.map((item, index) => (
          <span
            className={`${readability.pillMedium} rounded-xl bg-[var(--clue-background-pressed)] px-2 py-0.5`}
            key={`${formatJsonScalar(item) ?? "item"}-${index}`}
          >
            <FactValue value={item} />
          </span>
        ))}
      </span>
    );
  }

  const entries = jsonEntries(value);
  if (!entries.length) return <Absent />;

  return (
    <span className="flex flex-col gap-1">
      {entries.map(([key, entryValue]) => (
        <span className="flex flex-wrap items-baseline gap-1.5" key={key}>
          <span className="text-[var(--clue-content-subtle)]">
            {formatToken(key)}:
          </span>
          <FactValue value={entryValue} />
        </span>
      ))}
    </span>
  );
}

/**
 * The provenance line beneath a fact: who reported it, when it was observed,
 * and whether the merge considers it stale.
 *
 * `provider` is the raw backend source key — there is no source display-name
 * surface yet, so it is sentence-cased rather than mapped to a label an
 * adapter would have to invent.
 */
export function Provenance({
  freshness,
  observedAt,
  provider,
}: {
  freshness?: Freshness | null;
  observedAt: string | null;
  provider: string | null;
}) {
  const observed = formatIsoDate(observedAt);
  const parts = [
    provider ? formatToken(provider) : null,
    observed,
    freshness === "stale" ? "Past its freshness window" : null,
  ].filter(Boolean);

  if (!parts.length) return null;

  return (
    <span className="text-[var(--clue-content-subtle)]">{parts.join(" · ")}</span>
  );
}

/**
 * A registry-driven fact list.
 *
 * Fields are rendered generically off `fieldKey`, so an industry pack's custom
 * fields appear here with no schema change, no adapter change and no named
 * slot (FI-1 D-7).
 */
export function FactList({
  facts,
}: {
  facts: Array<{
    fieldKey: string;
    freshness?: Freshness | null;
    observedAt: string | null;
    provider: string | null;
    restricted?: boolean;
    value: JsonValue | null;
  }>;
}) {
  if (!facts.length) {
    return (
      <p className={`${readability.uiRegular} text-[var(--clue-content-subtle)]`}>
        No fields hold a value for this record yet.
      </p>
    );
  }

  return (
    <dl className="flex w-full flex-col gap-3">
      {facts.map((fact) => {
        const namespace = fieldKeyNamespace(fact.fieldKey);
        return (
          <div
            className="grid grid-cols-[minmax(0,160px)_minmax(0,1fr)] items-start gap-4"
            key={`${fact.fieldKey}-${fact.observedAt ?? "none"}`}
          >
            <dt
              className={`${readability.fieldLabel} min-w-0 text-[var(--clue-content-subtle)]`}
              title={fact.fieldKey}
            >
              {formatFieldKeyLabel(fact.fieldKey)}
              {namespace ? (
                <span className="block truncate opacity-70">{namespace}</span>
              ) : null}
            </dt>
            <dd className={`${readability.fieldValue} min-w-0`}>
              {fact.restricted ? (
                <Restricted />
              ) : fact.value === undefined || fact.value === null ? (
                <Absent />
              ) : (
                <FactValue value={fact.value} />
              )}
              <span className={`${readability.fieldLabel} mt-0.5 block`}>
                <Provenance
                  freshness={fact.freshness}
                  observedAt={fact.observedAt}
                  provider={fact.provider}
                />
              </span>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
