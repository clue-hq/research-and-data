export function FitScoreIndicator({ score }: { score: number | null }) {
  if (score === null) return <span aria-label="Fit score not provided">—</span>;
  const normalizedScore = Math.min(100, Math.max(0, score));

  return (
    <span
      aria-label={`Fit score ${normalizedScore} out of 100`}
      className="inline-flex items-center gap-1"
    >
      <svg
        aria-hidden="true"
        className="size-[13px] shrink-0 -rotate-90"
        viewBox="0 0 13 13"
      >
        <circle
          cx="6.5"
          cy="6.5"
          fill="none"
          r="6"
          stroke="var(--clue-ds-color-border-subtle)"
          strokeWidth="0.5"
        />
        <circle
          cx="6.5"
          cy="6.5"
          fill="none"
          pathLength="100"
          r="6"
          stroke="var(--clue-content-neutral)"
          strokeDasharray={`${normalizedScore} ${100 - normalizedScore}`}
          strokeLinecap="round"
          strokeWidth="1"
        />
      </svg>
      <span>{normalizedScore}</span>
    </span>
  );
}
