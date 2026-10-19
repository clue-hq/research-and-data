
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),
  quote: z.string().min(1),
  attribution: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <blockquote className="brand-heading max-w-[30ch] font-headline text-headline">{props.quote}</blockquote>
      <p className="mt-6 font-body text-body text-ink-secondary">{props.attribution}</p>
    </kit.Shell>
  );
}
