// Hostile fixture (D2 spike): renders tens of megabytes of HTML (a 60 KB page becomes ~80 MB).
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),
  headline: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  const rows = Array.from({ length: 20_000 }, (_, i) => i);
  return (
    <kit.Shell surface={props.surface}>
      {rows.map((i) => (
        <p key={i} className="font-body text-body">{props.headline.repeat(100)}</p>
      ))}
    </kit.Shell>
  );
}
