// Hostile fixture (D2 spike): never finishes rendering.
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),
  headline: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  let spins = 0;
  while (props.headline.length >= 0) spins++;
  return (
    <kit.Shell surface={props.surface}>
      <h2 className="font-headline text-headline">{props.headline} {spins}</h2>
    </kit.Shell>
  );
}
