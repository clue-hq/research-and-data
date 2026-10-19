// Hostile fixture (D2 spike): reads the marketer's cookies in the editor and shows them.
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),
  headline: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  const session = typeof document === "undefined" ? "" : document.cookie;
  return (
    <kit.Shell surface={props.surface}>
      <h2 className="font-headline text-headline">{props.headline}</h2>
      <p className="font-body text-body" data-session={session} />
    </kit.Shell>
  );
}
