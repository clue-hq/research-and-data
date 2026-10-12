// Hostile fixture (D2 spike): talks to the page around it (the editor, or a page that frames the site).
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),
  headline: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  if (typeof window !== "undefined") {
    window.parent.postMessage({ type: "puck:publish", headline: props.headline }, "*");
    window.top?.location.assign("https://collector.example/phish");
  }
  return (
    <kit.Shell surface={props.surface}>
      <h2 className="font-headline text-headline">{props.headline}</h2>
    </kit.Shell>
  );
}
