import type { ReactNode } from 'react';
import { FileText, Gift, Globe, Image as ImageIcon } from 'lucide-react';
import type { LibraryKind } from '../model/account-library';
import badge from '@/features/accounts/components/account-components.module.css';
import s from './account-artifact-library.module.css';

const types={gift:{label:'Gift',icon:Gift,tone:badge.badgeToneGrass},note:{label:'Card & note',icon:FileText,tone:badge.badgeToneOrange},page:{label:'Landing page',icon:Globe,tone:badge.badgeToneBlue},ad:{label:'Ad',icon:ImageIcon,tone:badge.badgeTonePink},file:{label:'Document',icon:FileText,tone:badge.badgeNeutral}};
export function MaterialBadge({kind,count}:{kind:LibraryKind;count?:number}) {
 const {label,icon:Icon,tone}=types[kind];
 return <span className={`${badge.badge} ${tone} ${s.materialBadge}`}><Icon size={12} strokeWidth={1.5}/>{label}{count!==undefined?` ${count}`:''}</span>;
}
export function ApprovalBadge({children,tone='neutral'}:{children:ReactNode;tone?:'neutral'|'positive'|'attention'}) {
 return <span className={`${badge.badge} ${tone==='positive'?badge.badgePositive:tone==='attention'?badge.badgeToneOrange:badge.badgeNeutral} ${s.materialBadge}`}>{children}</span>;
}
