import {useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {motion,useIsPresent} from 'motion/react';
import {Check} from 'lucide-react';
import {RoleTag,roleNames} from './RoleTag';
import type {Role} from '../api/types';
const roles:Role[]=['merchant','provider','platform','unknown'];
export function RoleMenu({anchor,value,busy,error,onChoose,onClose}:{anchor:HTMLElement;value:Role;busy:boolean;error:string;onChoose:(role:Role)=>void;onClose:()=>void}){
  const panel=useRef<HTMLDivElement>(null),latest=useRef({busy,onClose});latest.current={busy,onClose};
  const present=useIsPresent();
  const [position,setPosition]=useState({left:0,top:0});
  useLayoutEffect(()=>{
    let frame:number;
    const place=()=>{
      if(!anchor.isConnected){latest.current.onClose();return;}
      const box=anchor.getBoundingClientRect(),height=panel.current?.offsetHeight||220;
      const top=box.bottom+height+8<window.innerHeight?box.bottom+6:Math.max(8,box.top-height-6);
      const left=Math.max(8,Math.min(box.right-224,window.innerWidth-232));
      setPosition(old=>Math.abs(old.top-top)<.5&&Math.abs(old.left-left)<.5?old:{top,left});
      frame=requestAnimationFrame(place);
    };
    place();
    if(panel.current?.showPopover)panel.current.showPopover();
    panel.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    const outside=(event:PointerEvent)=>{
      if(!panel.current?.contains(event.target as Node)&&!anchor.contains(event.target as Node)&&!latest.current.busy)latest.current.onClose();
    };
    document.addEventListener('pointerdown',outside,true);
    return()=>{cancelAnimationFrame(frame);document.removeEventListener('pointerdown',outside,true);};
  },[anchor]);
  return createPortal(<motion.div ref={panel} popover={typeof HTMLElement.prototype.showPopover==='function'?'manual':undefined}
    className="role-menu" role="menu" aria-label="修改联系人身份" aria-hidden={!present} style={{...position,pointerEvents:present?'auto':'none'}}
    initial={{opacity:0,y:-4}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-3}} transition={{duration:.16}}
    onKeyDown={event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(!busy){onClose();anchor.focus();}return;}
      if(event.key==='Tab'&&!busy){onClose();anchor.focus();return;}
      if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
        event.preventDefault();const items=Array.from(panel.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]:not(:disabled)')||[]);if(!items.length)return;
        const index=items.indexOf(document.activeElement as HTMLButtonElement);
        const next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;
        items[next]?.focus();
      }
    }}>
    {roles.map(role=><button type="button" className="role-menu-option" key={role} role="menuitemradio" aria-label={roleNames[role]} aria-checked={value===role} tabIndex={value===role?0:-1} disabled={busy}
      onClick={()=>{if(role===value){onClose();anchor.focus();}else onChoose(role);}}><RoleTag role={role}/>{value===role&&<Check size={16}/>}</button>)}
    {busy&&<p className="field-hint" role="status">正在保存…</p>}
    {error&&<p className="error-banner" role="alert">{error}</p>}
  </motion.div>,anchor.closest('dialog')||document.body);
}
