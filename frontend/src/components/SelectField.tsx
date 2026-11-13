import { forwardRef, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { AnimatePresence, motion, useIsPresent, type HTMLMotionProps } from "motion/react";
import { Check, ChevronDown } from "lucide-react";

type Option = { value:string; label:string };
const SelectMenu=forwardRef<HTMLDivElement,HTMLMotionProps<'div'>>(function SelectMenu(props,ref){
  const present=useIsPresent();
  return <motion.div {...props} ref={ref} aria-hidden={!present} style={{...props.style,pointerEvents:present?'auto':'none'}}/>;
});
export function SelectField({label,options,id,value,onValueChange,disabled=false,required=false}:{
  label:string;options:Option[];id?:string;value:string;onValueChange:(value:string)=>void;disabled?:boolean;required?:boolean;
}) {
  const generated=useId(),fieldId=id||generated,listId=`${fieldId}-list`;
  const trigger=useRef<HTMLButtonElement>(null),panel=useRef<HTMLDivElement>(null),root=useRef<HTMLDivElement>(null);
  const [open,setOpen]=useState(false),[highlight,setHighlight]=useState(0);
  const [placement,setPlacement]=useState({top:0,left:0,width:0,maxHeight:280});
  const selected=options.findIndex(option=>option.value===value);
  const typeahead=useRef({text:"",at:0});
  const show=()=>{if(!disabled&&options.length){setHighlight(Math.max(0,selected));setOpen(true);}};
  const choose=(index:number)=>{if(options[index]){onValueChange(options[index].value);setOpen(false);trigger.current?.focus();}};
  useLayoutEffect(()=>{
    if(!open)return;
    const position=()=>{
      const box=trigger.current?.getBoundingClientRect();if(!box)return;
      const width=Math.min(box.width,window.innerWidth-16);
      const below=window.innerHeight-box.bottom-12,above=box.top-12;
      const desired=Math.min(288,options.length*40+12);
      const upward=below<desired&&above>below;
      const height=Math.min(desired,Math.max(80,upward?above:below));
      const next={top:upward?Math.max(8,box.top-height-6):box.bottom+6,
        left:Math.max(8,Math.min(box.left,window.innerWidth-width-8)),width,maxHeight:height};
      setPlacement(previous=>Object.keys(next).every(key=>Math.abs(previous[key as keyof typeof next]-next[key as keyof typeof next])<.5)?previous:next);
    };
    position();
    let frame:number;
    const follow=()=>{position();frame=requestAnimationFrame(follow);};
    frame=requestAnimationFrame(follow);
    if(panel.current?.showPopover&&!panel.current.matches(':popover-open'))panel.current.showPopover();
    const resize=()=>setOpen(false);
    window.addEventListener('resize',resize);
    const dismiss=(event:PointerEvent)=>{if(!root.current?.contains(event.target as Node))setOpen(false);};
    const visibility=typeof IntersectionObserver==='undefined'?null:new IntersectionObserver(entries=>{
      if(entries.some(entry=>!entry.isIntersecting))setOpen(false);
    });
    if(trigger.current)visibility?.observe(trigger.current);
    document.addEventListener('pointerdown',dismiss,true);
    return()=>{cancelAnimationFrame(frame);visibility?.disconnect();window.removeEventListener('resize',resize);document.removeEventListener('pointerdown',dismiss,true);};
  },[open,options.length]);
  useEffect(()=>{if(open)panel.current?.querySelector('[data-highlight="true"]')?.scrollIntoView({block:'nearest'});},[open,highlight]);
  useEffect(()=>{if(disabled)setOpen(false);},[disabled]);
  const keydown=(event:KeyboardEvent<HTMLButtonElement>)=>{
    if(event.key==='Escape'&&open){event.preventDefault();event.stopPropagation();setOpen(false);return;}
    if(event.key==='Tab'){setOpen(false);return;}
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
      event.preventDefault();
      if(!open){show();if(event.key==='Home')setHighlight(0);if(event.key==='End')setHighlight(options.length-1);return;}
      setHighlight(index=>event.key==='Home'?0:event.key==='End'?options.length-1:
        (index+(event.key==='ArrowDown'?1:-1)+options.length)%options.length);return;
    }
    if(open&&['Enter',' '].includes(event.key)){event.preventDefault();choose(highlight);return;}
    if(event.key.length===1&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&event.key!==' '){
      event.preventDefault();const now=Date.now();
      const text=(now-typeahead.current.at<700?typeahead.current.text:'')+event.key.toLocaleLowerCase();
      typeahead.current={text,at:now};
      const index=options.findIndex(option=>option.label.toLocaleLowerCase().startsWith(text));
      if(!open)show();if(index>=0)setHighlight(index);
    }
  };
  return <div className="field select-field" ref={root}>
    <label id={`${fieldId}-label`} htmlFor={fieldId}>{label}</label>
    <button type="button" ref={trigger} id={fieldId} className="form-control select-trigger" role="combobox"
      aria-labelledby={`${fieldId}-label`} aria-haspopup="listbox" aria-expanded={open} aria-controls={open?listId:undefined}
      aria-activedescendant={open?`${listId}-${highlight}`:undefined} aria-required={required} disabled={disabled}
      onClick={()=>open?setOpen(false):show()} onKeyDown={keydown}>
      <span>{options[selected]?.label||'请选择'}</span><ChevronDown size={16} className={open?'select-chevron expanded':'select-chevron'}/>
    </button>
    <AnimatePresence>{open&&<SelectMenu key="menu" ref={panel} popover={typeof HTMLElement.prototype.showPopover==='function'?'manual':undefined} id={listId} role="listbox"
      aria-labelledby={`${fieldId}-label`} className="select-menu" style={placement}
      initial={{opacity:0,y:-4}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-3}} transition={{duration:.16}}>
      {options.map((option,index)=><div role="option" key={option.value} id={`${listId}-${index}`}
        aria-selected={option.value===value} data-highlight={highlight===index} className="select-option"
        onPointerMove={()=>setHighlight(index)} onMouseDown={event=>event.preventDefault()} onClick={()=>choose(index)}>
        <span>{option.label}</span>{option.value===value&&<Check size={16} aria-hidden="true"/>}
      </div>)}
    </SelectMenu>}</AnimatePresence>
  </div>;
}
