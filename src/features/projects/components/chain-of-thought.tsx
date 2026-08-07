import {
  ChainOfThought as AiChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtImage,
  ChainOfThoughtSearchResult,
  ChainOfThoughtSearchResults,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import Image from "next/image";
import type { ProjectReasoningTrace } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

function TraceTags({
  tags,
}: {
  tags: ProjectReasoningTrace["targetSearch"]["tags"];
}) {
  return (
    <ChainOfThoughtSearchResults className={styles.thoughtTags}>
      {tags.map((tag) => (
        <ChainOfThoughtSearchResult className={styles.thoughtTag} key={tag.label}>
          {tag.logoPath ? (
            <Image
              alt=""
              height={12}
              src={tag.logoPath}
              style={{ height: 12, width: 12 }}
              width={12}
            />
          ) : null}
          {tag.label}
        </ChainOfThoughtSearchResult>
      ))}
    </ChainOfThoughtSearchResults>
  );
}

export function ChainOfThought({
  data,
  onToggle,
  open,
}: {
  data: ProjectReasoningTrace;
  onToggle: () => void;
  open: boolean;
}) {
  return (
    <AiChainOfThought
      className={styles.chainOfThought}
      onOpenChange={onToggle}
      open={open}
    >
      <ChainOfThoughtHeader
        className={styles.chainHeader}
        icon={<></>}
        indicator={<ProjectIcon className={styles.reasoningChevron} name="chevron-down" size={12} />}
      >
        {data.title}
      </ChainOfThoughtHeader>
      <ChainOfThoughtContent className={styles.chainContent}>
        <ChainOfThoughtStep
          className={styles.traceStep}
          icon={<ProjectIcon name="search" size={14} />}
          label={data.targetSearch.label}
        >
          <TraceTags tags={data.targetSearch.tags} />
        </ChainOfThoughtStep>
        <ChainOfThoughtStep
          className={styles.traceStep}
          icon={<ProjectIcon name="image" size={14} />}
          label={data.profile.label}
        >
          <ChainOfThoughtImage
            caption={data.profile.caption}
            className={styles.thoughtImage}
          >
            <Image
              alt={data.profile.imageAlt}
              height={151}
              src={data.profile.imagePath}
              width={151}
            />
          </ChainOfThoughtImage>
          <p className={styles.traceDetail}>{data.profile.detail}</p>
        </ChainOfThoughtStep>
        <ChainOfThoughtStep
          className={styles.traceStep}
          icon={<ProjectIcon name="search" size={14} />}
          label={data.recentSearch.label}
        >
          <TraceTags tags={data.recentSearch.tags} />
        </ChainOfThoughtStep>
      </ChainOfThoughtContent>
    </AiChainOfThought>
  );
}
