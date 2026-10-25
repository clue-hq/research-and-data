import { MailerSchema, type Mailer } from "../model/direct-mail";

/** Explicit local preview source, independent of the live API or training corpus. */
export async function loadPilotMailers(): Promise<Mailer[]> {
  const response = await fetch("/api/direct-mail/pilot", { cache: "no-store" });
  if (response.status === 204) return [];
  if (!response.ok) throw new Error("The local pilot examples could not be loaded.");
  const mailers = MailerSchema.array().max(10).parse(await response.json());
  if (mailers.some((mailer) => !mailer.id.startsWith("pilot-"))) throw new Error("Pilot records need isolated identifiers.");
  return mailers;
}
