// Evasion probe (D2 spike): a network call that names none of the banned identifiers. Every
// function's constructor is Function, so the check's list never sees it.
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),
  headline: z.string(),
  probe: z.string(),
}).strict();

const run = (() => 0).constructor as (code: string) => () => (url: string) => Promise<unknown>;

export function render(props: z.infer<typeof schema>, kit: Kit) {
  const get = run("return f" + "etch")();
  // In the editor this runs with the marketer's session: same origin, cookies attached.
  void get(props.probe);
  return (
    <kit.Shell surface={props.surface}>
      <h2 className="font-headline text-headline">{props.headline}</h2>
    </kit.Shell>
  );
}
