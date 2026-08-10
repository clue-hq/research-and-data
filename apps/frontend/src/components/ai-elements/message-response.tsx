"use client";

import { cn } from "@/lib/utils";
import type { ComponentProps } from "react";
import { Fragment } from "react";
import {
  parseStreamingMarkdown,
  type MarkdownBlock,
  type MarkdownInline,
} from "@/features/projects/model/streaming-markdown";

/**
 * `MessageResponse` / `MessageMarkdown` — the incremental Markdown renderer for
 * streamed assistant prose (charter §3.1's `text` row).
 *
 * Vendored presentation, like the rest of this folder, and deliberately
 * dependency-free: the catalog's renderer pulls a Markdown runtime, and §3.1's
 * ruling is that AI Elements stays *vendored presentation source*, never a
 * runtime transport or parser dependency. The parsing lives in
 * `features/projects/model/streaming-markdown.ts` as pure functions; this file
 * only turns blocks into elements.
 *
 * Two properties are load-bearing and both come from the parser:
 *
 * - **no raw-syntax flash** — while `streaming`, an inline construct whose
 *   closing delimiter has not arrived is not rendered at all, so the user never
 *   sees `**bo` resolve into bold a frame later;
 * - **no flicker** — blocks carry stable keys derived from their ordinal, so a
 *   growing document appends and updates in place instead of re-mounting, which
 *   is what preserves scroll position and any open disclosure beneath it.
 *
 * No raw HTML is ever rendered: every leaf below is text placed by React, so a
 * model cannot emit markup into the page.
 */

export type MessageMarkdownProps = ComponentProps<"div"> & {
  children: string;
  /** Derived from the part's own lifecycle — never a wire value, never a timer. */
  streaming?: boolean;
};

export const MessageMarkdown = ({
  children,
  className,
  streaming = false,
  ...props
}: MessageMarkdownProps) => {
  const blocks = parseStreamingMarkdown(children, { streaming });
  return (
    <div className={cn("clue-markdown", className)} {...props}>
      {blocks.map((block) => (
        <Block block={block} key={block.key} />
      ))}
    </div>
  );
};

export type MessageResponseProps = MessageMarkdownProps;

/** The assistant's final response body. Same renderer, named for its role. */
export const MessageResponse = ({ className, ...props }: MessageResponseProps) => (
  <MessageMarkdown className={cn("clue-response", className)} {...props} />
);

function Block({ block }: { block: MarkdownBlock }) {
  switch (block.type) {
    case "heading": {
      const level = Math.min(Math.max(block.level, 1), 6);
      const Tag = `h${level}` as "h1";
      return (
        <Tag>
          <Inlines tokens={block.inline} />
        </Tag>
      );
    }
    case "code":
      return (
        <pre data-language={block.language ?? undefined}>
          <code>{block.value}</code>
        </pre>
      );
    case "quote":
      return (
        <blockquote>
          <Inlines tokens={block.inline} />
        </blockquote>
      );
    case "list":
      return block.ordered ? (
        <ol>
          {block.items.map((item) => (
            <li key={item.key}>
              <Inlines tokens={item.inline} />
            </li>
          ))}
        </ol>
      ) : (
        <ul>
          {block.items.map((item) => (
            <li key={item.key}>
              <Inlines tokens={item.inline} />
            </li>
          ))}
        </ul>
      );
    case "paragraph":
      return (
        <p>
          <Inlines tokens={block.inline} />
        </p>
      );
  }
}

function Inlines({ tokens }: { tokens: readonly MarkdownInline[] }) {
  return (
    <>
      {tokens.map((token, index) => (
        <Fragment key={index}>
          <Inline token={token} />
        </Fragment>
      ))}
    </>
  );
}

function Inline({ token }: { token: MarkdownInline }) {
  switch (token.type) {
    case "strong":
      return <strong>{token.value}</strong>;
    case "em":
      return <em>{token.value}</em>;
    case "code":
      return <code>{token.value}</code>;
    case "link":
      // A model-authored href is untrusted: only http(s) is followed, anything
      // else renders as its label so a `javascript:` URL cannot become a link.
      return /^https?:\/\//i.test(token.href) ? (
        <a href={token.href} rel="noreferrer noopener" target="_blank">
          {token.value}
        </a>
      ) : (
        <>{token.value}</>
      );
    case "text":
      return <>{token.value}</>;
  }
}
