"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import {
  composeClarificationReply,
  type ClarificationAnswer,
} from "@/features/projects/model/clarification";
import type { ChatClarificationPart } from "@/features/projects/model/chat-parts";
import type { TurnContextReference } from "@/features/projects/model/chat-turn";
import styles from "./clarification-card.module.css";

/**
 * The clarification card (spec 2026-09-20 §2.5): a design document's
 * opening-move questions, asked above the composer and answered as one
 * ordinary chat message.
 *
 * The component is the surface and nothing else. Which questions are open and
 * what the answers read like as a message are Task 4's pure model
 * (`openClarification` / `composeClarificationReply`); this file holds only the
 * card's own state — where the user is, what they have chosen so far, and
 * whether the card is collapsed — and hands the composed message back through
 * `onSubmit`. There is no hidden payload and no new backend verb: the message
 * the agent receives is exactly the message the transcript shows.
 *
 * Founder rulings honoured here: "Something else…" is ALWAYS present (the
 * runtime's `allow_freeform` is deliberately ignored), and Skip names the
 * default rather than sending a blank.
 */

/** The card's answer key: one document's one question. */
function answerKey(documentId: string, questionId: string): string {
  return `${documentId}:${questionId}`;
}

/** The first question this document still owes an answer to, else 0. */
function firstUnansweredIndex(
  part: ChatClarificationPart,
  answers: ReadonlyMap<string, ClarificationAnswer>,
): number {
  const index = part.questions.findIndex(
    (question) => !answers.has(answerKey(part.documentId, question.id)),
  );
  return index === -1 ? 0 : index;
}

function unansweredCount(
  part: ChatClarificationPart,
  answers: ReadonlyMap<string, ClarificationAnswer>,
): number {
  return part.questions.filter(
    (question) => !answers.has(answerKey(part.documentId, question.id)),
  ).length;
}

/** `<title> · <account>` — the account suffix only when the document has one. */
function headerLabel(part: ChatClarificationPart): string {
  return part.accountName ? `${part.documentTitle} · ${part.accountName}` : part.documentTitle;
}

export function ClarificationCard({
  parts,
  onSubmit,
  onDismiss,
}: {
  parts: readonly ChatClarificationPart[];
  onSubmit: (text: string, contextRefs: TurnContextReference[]) => void;
  /** Fired when the user collapses the card with ✕; the chip stays rendered. */
  onDismiss?: () => void;
}) {
  const [documentIndex, setDocumentIndex] = useState(0);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [answers, setAnswers] = useState<ReadonlyMap<string, ClarificationAnswer>>(
    () => new Map(),
  );
  const [collapsed, setCollapsed] = useState(false);
  const [freeform, setFreeform] = useState("");
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const cardRef = useRef<HTMLDivElement | null>(null);
  // Set when an answer moved the card on. Answering unmounts the button that
  // was focused, which would drop focus to <body> and leave the digit/Esc keys
  // nowhere to land, so the next question takes the focus the last one had.
  // Only ever true after a keystroke or a click INSIDE the card, so the card
  // never steals focus from the composer on mount.
  const advanced = useRef(false);

  useEffect(() => {
    if (!advanced.current) return;
    advanced.current = false;
    const first = optionRefs.current[0];
    if (first) first.focus();
    else cardRef.current?.focus();
  }, [documentIndex, questionIndex]);

  const part = parts[documentIndex];
  if (!part) return null;
  // Both guards are runtime guards: the index types say these are always
  // present, but a part that arrived with no questions must not crash the
  // composer column.
  const question = part.questions[questionIndex];
  if (!question) return null;

  const key = answerKey(part.documentId, question.id);
  const recorded = answers.get(key);
  const remaining = unansweredCount(part, answers);
  const chipCount = remaining > 0 ? remaining : part.questions.length;

  /** Move to the question the card shows, carrying its recorded free text. */
  function goTo(nextDocumentIndex: number, nextQuestionIndex: number) {
    const nextPart = parts[nextDocumentIndex];
    const nextQuestion = nextPart?.questions[nextQuestionIndex];
    const nextAnswer = nextPart && nextQuestion
      ? answers.get(answerKey(nextPart.documentId, nextQuestion.id))
      : undefined;
    setDocumentIndex(nextDocumentIndex);
    setQuestionIndex(nextQuestionIndex);
    setFreeform(nextAnswer?.kind === "freeform" ? nextAnswer.value : "");
  }

  /**
   * Record one answer and move on — to the next question, to the next asking
   * document, or, after the last question of the last document, to the one
   * message that carries them all.
   *
   * The composed message is built from `next`, not from state: the last answer
   * must be IN the message that its own selection sends.
   */
  function record(answer: ClarificationAnswer) {
    const next = new Map(answers);
    next.set(key, answer);
    setAnswers(next);
    setFreeform("");

    if (questionIndex + 1 < part.questions.length) {
      advanced.current = true;
      setQuestionIndex(questionIndex + 1);
      return;
    }
    if (documentIndex + 1 < parts.length) {
      advanced.current = true;
      setDocumentIndex(documentIndex + 1);
      setQuestionIndex(0);
      return;
    }
    const reply = composeClarificationReply(
      parts.map((item) => ({
        part: item,
        answers: new Map(
          item.questions
            .map((entry) => [entry.id, next.get(answerKey(item.documentId, entry.id))] as const)
            .filter((pair): pair is readonly [string, ClarificationAnswer] => pair[1] !== undefined),
        ),
      })),
    );
    onSubmit(reply.text, reply.contextRefs);
  }

  function submitFreeform() {
    const text = freeform.trim();
    if (!text) return;
    record({ kind: "freeform", value: text });
  }

  function skip() {
    record({ kind: "skipped", default: question.default });
  }

  /** ↑↓ moves focus between the option buttons; a digit jumps straight to one. */
  function onCardKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    // The free-text row owns its own keys: a "1" typed there is a character,
    // never option one, and its Enter submits the text.
    if (event.target instanceof HTMLInputElement) {
      if (event.key === "Escape") {
        event.preventDefault();
        skip();
      }
      return;
    }
    const options = question.options;
    if (event.key === "Escape") {
      event.preventDefault();
      skip();
      return;
    }
    if (options.length === 0) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const focused = optionRefs.current.findIndex((node) => node === document.activeElement);
      const step = event.key === "ArrowDown" ? 1 : -1;
      const start = focused === -1 ? (step === 1 ? -1 : 0) : focused;
      const nextIndex = (start + step + options.length) % options.length;
      optionRefs.current[nextIndex]?.focus();
      return;
    }
    if (/^[1-9]$/.test(event.key)) {
      const index = Number(event.key) - 1;
      const value = options[index];
      if (value === undefined) return;
      event.preventDefault();
      record({ kind: "option", value });
    }
    // Enter is left to the focused <button>: a real button already activates
    // on Enter, and handling it here too would answer the question twice.
  }

  if (collapsed) {
    return (
      <button
        className={styles.chip}
        onClick={() => {
          setCollapsed(false);
          goTo(documentIndex, firstUnansweredIndex(part, answers));
        }}
        type="button"
      >
        {`${chipCount} ${chipCount === 1 ? "question" : "questions"} from ${part.documentTitle} — answer`}
      </button>
    );
  }

  return (
    <div className={styles.wrapper}>
      {parts.length > 1 ? (
        <div className={styles.strip}>{`${parts.length} designs have questions`}</div>
      ) : null}
      <div className={styles.card} onKeyDown={onCardKeyDown} ref={cardRef} tabIndex={-1}>
        <header className={styles.header}>
          <span className={styles.headerTitle}>{headerLabel(part)}</span>
          <span className={styles.pager}>
            <button
              aria-label="Previous question"
              className={styles.pagerButton}
              disabled={questionIndex === 0}
              onClick={() => goTo(documentIndex, questionIndex - 1)}
              type="button"
            >
              ‹
            </button>
            <span className={styles.pagerLabel}>
              {`${questionIndex + 1} of ${part.questions.length}`}
            </span>
            <button
              aria-label="Next question"
              className={styles.pagerButton}
              disabled={questionIndex + 1 >= part.questions.length}
              onClick={() => goTo(documentIndex, questionIndex + 1)}
              type="button"
            >
              ›
            </button>
          </span>
          <button
            aria-label="Collapse questions"
            className={styles.collapseButton}
            onClick={() => {
              setCollapsed(true);
              onDismiss?.();
            }}
            type="button"
          >
            ✕
          </button>
        </header>
        <p aria-live="polite" className={styles.question}>
          {question.question}
        </p>
        {question.whyItMatters ? (
          <p className={styles.why}>{question.whyItMatters}</p>
        ) : null}
        {question.options.length > 0 ? (
          <div className={styles.options}>
            {question.options.map((option, index) => (
              <button
                className={styles.option}
                data-selected={
                  recorded?.kind === "option" && recorded.value === option ? "true" : undefined
                }
                key={option}
                onClick={() => record({ kind: "option", value: option })}
                ref={(node) => {
                  optionRefs.current[index] = node;
                }}
                type="button"
              >
                <span className={styles.optionIndex}>{index + 1}</span>
                <span className={styles.optionLabel}>{option}</span>
              </button>
            ))}
          </div>
        ) : null}
        <div className={styles.footer}>
          <input
            aria-label="Something else"
            className={styles.freeform}
            onChange={(event) => setFreeform(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return;
              event.preventDefault();
              submitFreeform();
            }}
            placeholder="Something else…"
            value={freeform}
          />
          <button
            className={styles.skip}
            onClick={skip}
            title={`Skip — use ${question.default}`}
            type="button"
          >
            Skip
          </button>
        </div>
      </div>
      <p className={styles.hint}>
        ↑↓ to navigate · Enter to select · Esc to skip
      </p>
    </div>
  );
}

/**
 * The same questions, read-only, once the turn that asked is no longer the
 * latest (spec §2.5, "Historical rendering"). No controls: the answer — or the
 * silence that let the defaults stand — is already in the transcript below it.
 */
export function ClarificationHistoryCard({ part }: { part: ChatClarificationPart }) {
  return (
    <div className={styles.historyCard}>
      <div className={styles.historyTitle}>{headerLabel(part)}</div>
      <ul className={styles.historyQuestions}>
        {part.questions.map((question) => (
          <li key={question.id}>
            <span>{question.question}</span>
            <small>{`Default: ${question.default}`}</small>
          </li>
        ))}
      </ul>
      <small className={styles.historyNote}>answered in your next message</small>
    </div>
  );
}
