'use client';
import Image from 'next/image';
import { FileText } from 'lucide-react';
import { ProductImage } from '@/features/direct-mail/components/product-image';
import { CardFace, MailerPreview } from '@/features/direct-mail/components/mailer-preview';
import { money, selectedGift, type DirectMailState } from '@/features/direct-mail/model/direct-mail';
import { ArtifactPreview } from '@/features/orchestration/components/artifact-library';
import type { WorkspaceState } from '@/features/orchestration/model/workspace';
import type { LibraryItem } from '../model/account-library';
import s from './account-artifact-library.module.css';
import { RecipientPagePreview } from './outreach-review';

/** Preview the saved version, including the immutable content in an approved send. */
export function LibraryPreview({item,mail,workspace,compact=false}:{item:LibraryItem;mail:DirectMailState;workspace:WorkspaceState;compact?:boolean}) {
 const m=item.mailer,a=m?.approval,gift=m&&(a?.gift??selectedGift(m));
 const card=a?.card??mail.cards.find(c=>c.id===m?.cardId),style=a?.style??mail.styles.find(s=>s.id===m?.styleId);
 if(item.file)return <div className={s.filePreview}><Image src={item.file.thumbnailPath} alt={compact?'':item.title} fill sizes={compact?'350px':'800px'} unoptimized className="object-contain"/></div>;
 if(item.kind==='gift'&&gift)return <div className={s.giftPreview}><ProductImage src={gift.image} alt={compact?'':gift.name}/>{!compact?<div><h2>{gift.name}</h2><p>{gift.variant}</p><p>{money(gift.priceCents)} · {gift.merchant}</p><p className={s.subtle}>{gift.rationale}</p></div>:null}</div>;
 if(item.kind==='note'&&m&&card)return <div className={s.notePreview}>{compact?<CardFace card={card} style={style} note={a?.note??m.note} signature={a?.signature??m.signature}/>:<MailerPreview card={card} style={style} note={a?.note??m.note} signature={a?.signature??m.signature}/>}</div>;
 if(item.page&&m&&!compact)return <RecipientPagePreview page={item.page} mailer={m}/>;
 if(item.creative&&!compact)return <ArtifactPreview asset={item.creative} data={workspace} mail={mail}/>;
 const page=item.page??item.creative;
 if(page)return <div className={`${s.pagePreview} ${item.kind==='ad'?s.adPreview:''}`} data-compact={compact}>
  <header><strong>Clue</strong><span>{item.kind==='ad'?'Sponsored':`For ${m?.recipient.company??workspace.accounts.find(a=>a.id===item.accountId)?.name??'this account'}`}</span></header>
  <div><span className={s.eyebrow}>{item.kind==='ad'?'Account campaign':`A working session${m?` with ${m.signature.split('\n')[0]}`:''}`}</span><h2>{page.headline}</h2><p>{page.body}</p><span className={s.previewCta}>{page.cta}</span></div>
  {!compact&&item.page&&m?<footer>{m.signature.split('\n')[0]}<span>Your account contact</span></footer>:null}
 </div>;
 return <div className={s.filePreview}><FileText size={30} strokeWidth={1.25}/></div>;
}
