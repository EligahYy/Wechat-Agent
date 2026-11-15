import {useEffect,useLayoutEffect,useRef,type RefObject} from 'react';
/** Only directed user scrolling can fetch another window; preserve prepended anchors. */
export function useMessageEdges(scroll:RefObject<HTMLDivElement|null>,items:unknown,before:string|null|undefined,after:string|null|undefined,busy:boolean,load:(before:boolean)=>Promise<void>,reset:string){
 const intent=useRef(0),lock=useRef(false),anchor=useRef<{id:string;top:number}|null>(null);
 useEffect(()=>{intent.current=0;anchor.current=null;lock.current=false;},[reset]);
 useLayoutEffect(()=>{const saved=anchor.current,node=scroll.current;if(!saved||!node)return;anchor.current=null;const message=Array.from(node.querySelectorAll<HTMLElement>('[data-message]')).find(item=>item.dataset.message===saved.id);if(message)node.scrollTop+=message.getBoundingClientRect().top-saved.top;},[items]);
 useEffect(()=>{const node=scroll.current;if(!node)return;let frame=0,direction=0,lastTop=node.scrollTop,touchY:number|null=null,dragging=false;
 const check=()=>{if(performance.now()>intent.current||busy||lock.current)return;
  const previous=direction<0&&node.scrollTop<100&&!!before,next=direction>0&&node.scrollTop+node.clientHeight>node.scrollHeight-100&&!!after;if(!previous&&!next)return;
  lock.current=true;intent.current=0;
  if(previous){const first=Array.from(node.querySelectorAll<HTMLElement>('[data-message]')).find(item=>item.getBoundingClientRect().bottom>node.getBoundingClientRect().top);if(first)anchor.current={id:first.dataset.message!,top:first.getBoundingClientRect().top};}
  void load(previous).finally(()=>{lock.current=false;});};
 const onScroll=()=>{const delta=node.scrollTop-lastTop;lastTop=node.scrollTop;if(dragging){direction=Math.sign(delta);intent.current=performance.now()+1200;}check();};
 const gesture=(event:Event)=>{
  if((event.target as HTMLElement)?.closest('input,textarea,[role="listbox"]'))return;
  if(event.type==='pointerdown'){dragging=event.target===node;return;}
  if(event instanceof WheelEvent)direction=Math.sign(event.deltaY);
  else if(event instanceof KeyboardEvent){if(!['ArrowUp','ArrowDown','PageUp','PageDown','Home','End'].includes(event.key))return;direction=['ArrowUp','PageUp','Home'].includes(event.key)?-1:1;}
  else if(event instanceof TouchEvent){const y=event.touches[0]?.clientY;if(event.type==='touchstart'){touchY=y;return;}direction=touchY===null?0:Math.sign(touchY-y);touchY=y;}
  intent.current=performance.now()+1200;cancelAnimationFrame(frame);frame=requestAnimationFrame(check);
 };
 const release=()=>{dragging=false;};node.addEventListener('scroll',onScroll);window.addEventListener('pointerup',release);
 for(const event of ['wheel','touchstart','touchmove','keydown','pointerdown'])node.addEventListener(event,gesture,{passive:true});
 return()=>{cancelAnimationFrame(frame);node.removeEventListener('scroll',onScroll);window.removeEventListener('pointerup',release);for(const event of ['wheel','touchstart','touchmove','keydown','pointerdown'])node.removeEventListener(event,gesture);};
 },[scroll,items,before,after,busy,load]);
}
