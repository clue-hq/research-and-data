"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { FileText, Gift, Globe, Image as ImageIcon, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select-field";
import { useDirectMail } from "@/features/direct-mail/hooks/use-direct-mail";
import { isDraft, estimate, money, selectedGift } from "@/features/direct-mail/model/direct-mail";
import { MailerReview } from "@/features/direct-mail/components/mailer-review";
import { MailerTracking } from "@/features/direct-mail/components/mailer-tracking";
import { ProductImage } from "@/features/direct-mail/components/product-image";
import { useWorkspace } from "@/features/orchestration/hooks/use-workspace";
import { ArtifactPreview } from "@/features/orchestration/components/artifact-library";
import { buildMaterials, materialKinds, queryMaterials, materialEntry, type Material } from "../model/materials";
import mailStyles from "@/features/direct-mail/components/direct-mail.module.css";
import s from "./materials.module.css";

const icons = {gift:Gift,note:FileText,page:Globe,ad:ImageIcon};

/** Shared browser for chat Gallery, account Artifacts and the workspace library. */
export function LegacyMaterialsBrowser({ projectId, accountId:fixedAccount, initialAccount, onBackToAccounts, designFiles, title="Gallery" }: {
 projectId?:string; accountId?:string; initialAccount?:string; onBackToAccounts?:()=>void; designFiles?:ReactNode; title?:string;
}) {
 const c=useDirectMail(), w=useWorkspace(), params=useSearchParams();
 const entry=materialEntry({fixedAccount,tableAccount:initialAccount,routeAccount:params.get("materialsAccount"),routeMaterial:params.get("material")});
 const [account,setAccount]=useState(entry.accountId);
 const [contact,setContact]=useState("all"), [kind,setKind]=useState("all"), [status,setStatus]=useState("all");
 const [search,setSearch]=useState(""), [page,setPage]=useState(1), [design,setDesign]=useState(false);
 const [selectedId,setSelected]=useState<string|null>(entry.materialId);
 const rows=useMemo(()=>w.data && c.data ? buildMaterials(w.data,c.data).filter(r=>!projectId || r.projectId===projectId):[],[w.data,c.data,projectId]);
 const scopedAccount=fixedAccount ?? account;
 const result=queryMaterials(rows,{accountId:scopedAccount,contactId:contact,kind,status,search,page});
 const accounts=Array.from(new Map(rows.map(r=>[r.accountId,{value:r.accountId,label:r.accountName}])).values()).sort((a,b)=>a.label.localeCompare(b.label));
 const people=Array.from(new Map(rows.filter(r=>r.contactId && (scopedAccount==="all" || r.accountId===scopedAccount)).map(r=>[r.contactId!,{value:r.contactId!,label:r.recipient!}])).values());
 const selection=rows.find(r=>r.id===selectedId && (scopedAccount==="all" || r.accountId===scopedAccount));
 const accountPlan=w.data?.accounts.find(a=>a.id===scopedAccount);
 const error=c.error ?? w.error;
 function change(set:(value:string)=>void,value:string) {set(value);setPage(1);}
 function open(row:Material) {setSelected(row.id);}
 const related=selection ? rows.filter(r=>r.accountId===selection.accountId && (!r.contactId || r.contactId===selection.contactId)) : [];
 return <section className={`${s.surface} ${mailStyles.screen}`} aria-label="Account materials">
  <div className={s.scroll}>
   <header className={s.header}>
    <div className={s.breadcrumb}>
     {onBackToAccounts ? <button onClick={onBackToAccounts}>Target accounts</button> : null}
     <button onClick={()=>{setSelected(null);setDesign(false);if(!selectedId && !fixedAccount)setAccount("all");}} aria-label="Back to materials">{title}</button>
     {selection ? <span>{selection.accountName} · {materialKinds[selection.kind]}</span> : scopedAccount!=="all" ? <span>{accountPlan?.name ?? accounts.find(a=>a.value===scopedAccount)?.label ?? "Account"}</span> : null}
    </div>
    {designFiles ? <Button variant="transparent" size="sm" onClick={()=>{setDesign(!design);setSelected(null);}}>{design ? "Campaign materials" : "Design files & documents"}</Button> : null}
   </header>
   {error ? <div role="alert" className={mailStyles.notice}>{error}<Button variant="transparent" size="sm" onClick={()=>{void c.reload();void w.reload();}}>Retry</Button></div> : null}
   {!w.data || !c.data ? <p className={s.empty} role="status">{error ? "Materials could not be loaded." : "Loading materials…"}</p> : design ? designFiles : selection ? <div className={s.detail}>
    <div className={s.context}><div><strong>{selection.accountName}</strong><span>{selection.recipient ?? "Account-wide material"}</span></div><Button variant="transparent" size="sm" onClick={()=>setSelected(null)}>Back to materials</Button></div>
    <nav className={s.related} aria-label="Connected materials">{related.map(row=><button key={row.id} aria-current={row.id===selection.id?"page":undefined} onClick={()=>open(row)}>{materialKinds[row.kind]}{row.kind==="gift" && row.mailer && !isDraft(row.mailer)?" & tracking":""}</button>)}</nav>
    {selection.mailer && (selection.kind==="gift" || selection.kind==="note") ? <>
     {isDraft(selection.mailer) ? <MailerReview key={selection.id} controller={c} saved={selection.mailer} initialStep={selection.kind==="note"?1:0} onBack={()=>setSelected(null)} onOpenPage={related.some(r=>r.kind==="page") ? ()=>{open(related.find(r=>r.kind==="page")!);} : undefined} queueHref="/direct-mail" /> : <MailerTracking controller={c} mailer={selection.mailer} onOpenPage={related.some(r=>r.kind==="page") ? ()=>{open(related.find(r=>r.kind==="page")!);} : undefined} />}
    </> : selection.asset ? <div className={s.creative}><ArtifactPreview asset={selection.asset} data={w.data} mail={c.data} /><section className={mailStyles.section}><h2>Connected to this material</h2><p className={mailStyles.small}>{selection.kind==="ad" ? "An account-wide ad introduces the campaign. Each recipient’s gift links to their own landing page." : "This page is the destination for the recipient’s card. The printed QR is assigned and checked during preparation."}</p><p className={`${mailStyles.caption} mt-2`}>{selection.mailer ? `Sender: ${selection.mailer.approval?.signature.split("\n")[0] ?? selection.mailer.signature.split("\n")[0]}` : "Audience: target account buying committee"}</p></section></div> : null}
   </div> : selectedId ? <div className={s.empty}><p>This material is unavailable in this account.</p><Button variant="transparent" size="sm" onClick={()=>setSelected(null)}>Back to materials</Button></div> : <div className={s.content}>
    <div className={mailStyles.heading}><div><h1 className={mailStyles.title}>{accountPlan?.name ?? title}</h1><p className={`${mailStyles.small} ${mailStyles.subtle}`}>{accountPlan ? `${people.length} ${people.length===1?"recipient":"recipients"} · ${rows.filter(r=>r.accountId===scopedAccount).length} materials` : "Gifts, notes and campaign creative, together by account."}</p></div>{accountPlan ? <div className={s.owner}><span>Account owner</span><strong>{w.data.people.find(p=>p.id===accountPlan.ownerId)?.name}</strong><span>{accountPlan.territory} territory</span></div> : null}</div>
    {accountPlan?.id==="snowflake" ? <p className={`${mailStyles.caption} ${s.demoCaption}`}>Illustrative campaign · recipient names and research are fictional.</p> : null}
    <nav className={mailStyles.tabs} aria-label="Material status">{[["all","All materials"],["review","Needs review"],["approved","Approved"],["tracking","In fulfillment"]].map(([value,label])=><button key={value} className={mailStyles.tab} aria-current={status===value?"page":undefined} onClick={()=>change(setStatus,value)}>{label}</button>)}</nav>
    <div className={mailStyles.toolbar}><label className={mailStyles.search}><Search size={15}/><input aria-label="Search materials" value={search} placeholder="Search materials or recipients" onChange={e=>change(setSearch,e.target.value)}/></label><div className={s.filters}>
     {!fixedAccount ? <SelectField ariaLabel="Materials account" value={account} options={[{value:"all",label:"All accounts"},...accounts]} onValueChange={value=>{change(setAccount,value);setContact("all");}}/> : null}
     <SelectField ariaLabel="Materials recipient" value={contact} options={[{value:"all",label:"All recipients"},...people]} onValueChange={value=>change(setContact,value)}/>
     <SelectField ariaLabel="Material type" value={kind} options={[{value:"all",label:"All types"},...Object.entries(materialKinds).map(([value,label])=>({value,label}))]} onValueChange={value=>change(setKind,value)}/>
    </div></div>
    {result.total ? <div className={mailStyles.tableWrap}><table className={`${mailStyles.table} ${s.table}`}><caption className="sr-only">Account campaign materials</caption><thead><tr><th>Material</th><th>Account / recipient</th><th>Status</th><th>Details</th><th><span className="sr-only">Open material</span></th></tr></thead><tbody>{result.rows.map(row=>{
     const Icon=icons[row.kind], gift=row.mailer && selectedGift(row.mailer);
     return <tr key={row.id}><td><button className={s.materialButton} aria-label={`Preview ${materialKinds[row.kind]} for ${row.recipient ?? row.accountName}`} onClick={()=>open(row)}><span className={s.thumbnail}>{row.kind==="gift" && gift ? <ProductImage src={gift.image} alt="" className={s.image}/> : row.kind==="note" && row.mailer ? <FileText size={21} strokeWidth={1.3}/> : <Icon size={21} strokeWidth={1.3}/>}</span><span><strong>{row.kind==="gift" ? gift?.name ?? "3 gift options" : row.title}</strong><span>{materialKinds[row.kind]}</span></span></button></td><td><button className={s.accountLink} onClick={()=>{if(!fixedAccount){change(setAccount,row.accountId);setContact("all");}}}>{row.accountName}</button><p className={mailStyles.caption}>{row.recipient ?? "Shared across the account"}</p></td><td><span className={s.status} data-review={row.status==="Needs review" || row.status==="Ready to approve"}>{row.status}</span></td><td className={mailStyles.small}>{row.kind==="gift" && row.mailer ? money(estimate(row.mailer)) : `Version ${row.version}`}<p className={mailStyles.caption}>{row.kind==="gift" ? "Estimated total" : row.kind==="page" ? "Not published" : row.kind==="ad" ? "Not launched" : row.mailer?.approval ? "Approved with gift" : "Included with gift"}</p></td><td><Button variant="transparent" size="sm" aria-label={`Open ${materialKinds[row.kind]} for ${row.recipient ?? row.accountName}`} onClick={()=>open(row)}>{row.mailer && row.kind==="gift" && !isDraft(row.mailer)?"Track":"Review"}</Button></td></tr>;
    })}</tbody></table></div> : <div className={s.empty}><p>No materials match this view.</p><p className={mailStyles.caption}>Prepared gifts and creative appear here when they are linked to an account.</p><Button variant="transparent" size="sm" onClick={()=>{setSearch("");setKind("all");setStatus("all");setContact("all");}}>Clear filters</Button></div>}
    <footer className={mailStyles.pagination}><span>{result.total} materials</span><div className={mailStyles.row}><Button variant="transparent" size="sm" disabled={result.page===1} onClick={()=>setPage(result.page-1)}>Previous</Button><span>{result.page} / {result.pages}</span><Button variant="transparent" size="sm" disabled={result.page===result.pages} onClick={()=>setPage(result.page+1)}>Next</Button></div></footer>
   </div>}
  </div>
 </section>;
}
