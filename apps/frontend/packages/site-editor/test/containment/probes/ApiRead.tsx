// Containment probe (Lane C, Review focus 6): an agent section that reads the APP's API with the
// marketer's cookies attached. The editor's policy must stop it before it leaves the frame.
import { z } from "zod";

export const schema = z.object({ id: z.string(), headline: z.string(), probe: z.string() }).strict();

export function render(props: z.infer<typeof schema>) {
  void fetch(props.probe, { credentials: "include" });
  return (
    <section>
      <h2>{props.headline}</h2>
    </section>
  );
}
