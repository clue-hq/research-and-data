"use client";
import { useState } from "react";
import { Maximize2 } from "lucide-react";
import { matchingCardArtwork, type CardAsset, type HandwritingStyle } from "../model/direct-mail";
import { MailDialog } from "./mail-ui";
import styles from "./direct-mail.module.css";

export function CardFace({ card, style, note = "", signature = "", face = "message" }: { card: CardAsset; style?: HandwritingStyle; note?: string; signature?: string; face?: "front" | "message" }) {
  const artwork = matchingCardArtwork(card, style, note, signature);
  const image = face === "front" ? card.frontUrl : artwork?.url ?? card.backUrl;
  return <div className={styles.cardWrap}><div className={styles.card} data-paper={card.paper} data-front-layout={face === "front" ? card.frontLayout : undefined} aria-label={`${card.name}, ${face === "front" ? "front" : "message side"}`}>
    {/* Card artwork can be a user-uploaded data URL; Next image optimization is not appropriate. */}
    {/* eslint-disable-next-line @next/next/no-img-element */}
    {image ? <img className={styles.cardImage} src={image} alt="" /> : null}
    {face === "message" ? artwork ? <span className="sr-only">{note}{"\n\n"}{signature}</span> : <div className={styles.writing} style={{ left: `${card.writingArea.x}%`, top: `${card.writingArea.y}%`, width: `${card.writingArea.width}%`, height: `${card.writingArea.height}%`, fontFamily: style ? `"${style.family}", cursive` : "cursive" }}>{note}{"\n\n"}{signature}</div> : null}
    {card.branding && face === "front" ? <div className={styles.cardBrandFooter}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={card.branding.logoUrl} alt={card.branding.name || card.name} />
      <span>{card.branding.line}</span>
    </div> : null}
    {card.branding && face === "message" ? <>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className={styles.cardBrandMark} src={card.branding.markUrl} alt={card.branding.name || card.name} />
      <div className={styles.cardQr}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={card.branding.qrImageUrl} alt={`QR code for ${card.branding.qrDestination}`} />
        <span>{new URL(card.branding.qrDestination).hostname.replace(/^www\./, "")}</span>
      </div>
    </> : null}
  </div></div>;
}
export function MailerPreview({ card, style, note, signature }: { card?: CardAsset; style?: HandwritingStyle; note: string; signature: string }) {
  const [face, setFace] = useState<"front" | "message">("message");
  const [zoom, setZoom] = useState(false);
  if (!card) return null;
  const artwork = matchingCardArtwork(card, style, note, signature);
  const preview = <CardFace card={card} style={style} note={note} signature={signature} face={face} />;
  const faceControls = <div className={styles.row} role="group" aria-label="Card side"><button type="button" aria-pressed={face === "front"} onClick={() => setFace("front")}>Front</button><button type="button" aria-pressed={face === "message"} onClick={() => setFace("message")}>Message</button></div>;
  return <div><div className={styles.cardControls}>{faceControls}<button type="button" aria-label="Enlarge card preview" onClick={() => setZoom(true)}><Maximize2 size={14} /></button></div>{preview}<p className={`${styles.caption} mt-2`}>6 × 4 in · {artwork ? "Handwritten artwork" : style?.name ?? "Choose handwriting"}</p>
    {zoom ? <MailDialog title="Card preview" description={card.name} close={() => setZoom(false)} wide><div className={styles.cardControls}>{faceControls}</div>{preview}</MailDialog> : null}
  </div>;
}
