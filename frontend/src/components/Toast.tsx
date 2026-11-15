import {useLayoutEffect,useRef} from 'react';
import {createPortal} from 'react-dom';

/** Keep feedback above native dialogs without moving keyboard focus. */
export function Toast({message,onDismiss}:{message:string;onDismiss:()=>void}){
  const ref=useRef<HTMLButtonElement>(null);
  const dialog=Array.from(document.querySelectorAll<HTMLDialogElement>('dialog[open]')).filter(node=>!node.classList.contains('dialog-closing')).at(-1);
  useLayoutEffect(()=>{
    const node=ref.current;
    if(node?.showPopover&&!node.matches(':popover-open'))node.showPopover();
  },[message,dialog]);
  return createPortal(<button ref={ref} type="button" popover={typeof HTMLElement.prototype.showPopover==='function'?'manual':undefined} className={`toast${dialog?' toast-modal':''}`} role="status" onClick={onDismiss}>{message}</button>,dialog||document.body);
}
