import type {ButtonHTMLAttributes,ReactNode} from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import {useTranslation} from 'react-i18next';
import {X} from 'lucide-react';
import {clsx} from 'clsx';
import {twMerge} from 'tailwind-merge';
export const cn=(...inputs:Parameters<typeof clsx>)=>twMerge(clsx(inputs));
export function Button({className,children,variant='primary',...props}:ButtonHTMLAttributes<HTMLButtonElement>&{variant?:'primary'|'secondary'|'ghost'|'danger'}){return <button className={cn('btn',`btn-${variant}`,className)} {...props}>{children}</button>}
export function Dialog({open,onOpenChange,title,children}:{open:boolean;onOpenChange:(v:boolean)=>void;title:string;children:ReactNode}){const {i18n}=useTranslation();return <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}><DialogPrimitive.Portal><DialogPrimitive.Overlay className="dialog-overlay"/><DialogPrimitive.Content className="dialog-content" aria-describedby={undefined}><DialogPrimitive.Title className="dialog-title">{title}</DialogPrimitive.Title><DialogPrimitive.Close className="icon-button dialog-close" aria-label={i18n.language==='kk'?'Жабу':'Закрыть'}><X size={19}/></DialogPrimitive.Close>{children}</DialogPrimitive.Content></DialogPrimitive.Portal></DialogPrimitive.Root>}
export function Badge({children,tone='green'}:{children:ReactNode;tone?:string}){return <span className={`badge badge-${tone}`}>{children}</span>}
export function Empty({children}:{children:ReactNode}){return <div className="empty">{children}</div>}
