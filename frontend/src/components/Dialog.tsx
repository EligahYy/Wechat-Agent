import { useLayoutEffect, useId, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
export function Dialog({
  open,
  title,
  onClose,
  children,
  footer,
  headerActions,
  status,
  wide = false,
}: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  headerActions?: ReactNode;
  status?: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null),
    previous = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const [closing, setClosing] = useState(false);
  const body=useRef<HTMLDivElement>(null),content=useRef<HTMLDivElement>(null);
  const [bodyHeight,setBodyHeight]=useState<number>();
  useLayoutEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open) {
      if (!dialog.open)
        previous.current = document.activeElement as HTMLElement;
      setClosing(false);
      if (!dialog.open) {
        if (dialog.showModal) dialog.showModal();
        else dialog.setAttribute("open", "");
      }
      const target = dialog.querySelector<HTMLElement>(
        '[autofocus],button,input,[tabindex="0"]',
      );
      target?.focus();
    } else if (dialog.open) {
      setClosing(true);
      const timer = window.setTimeout(() => {
        if (dialog.close) dialog.close();
        else dialog.removeAttribute("open");
        previous.current?.focus();
      }, 180);
      return () => clearTimeout(timer);
    }
  }, [open]);
  useLayoutEffect(()=>{
    const dialog=ref.current,node=content.current,scroll=body.current;
    if(!open||!dialog||!node||!scroll)return;
    const measure=()=>{
      if(!dialog.open)return;
      const padding=getComputedStyle(scroll);
      const chrome=Array.from(dialog.children).filter(child=>child.matches(".dialog-header,.dialog-status,.dialog-footer"))
        .reduce((height,child)=>height+(child as HTMLElement).offsetHeight,0);
      const max=parseFloat(getComputedStyle(dialog).maxHeight)||window.innerHeight-48;
      const natural=node.offsetHeight+parseFloat(padding.paddingTop)+parseFloat(padding.paddingBottom);
      const next=Math.max(0,Math.min(natural,max-chrome-2));
      setBodyHeight(previous=>previous!==undefined&&Math.abs(previous-next)<1?previous:next);
    };
    measure();window.addEventListener('resize',measure);
    const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(measure);
    observer?.observe(node);
    for(const child of dialog.children)if(child!==scroll)observer?.observe(child);
    return()=>{observer?.disconnect();window.removeEventListener('resize',measure);};
  },[open,!!status,!!footer]);
  return (
    <dialog
      ref={ref}
      className={`dialog glass ${wide ? "dialog-wide" : ""} ${closing ? "dialog-closing" : ""}`}
      aria-modal="true"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          const box = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < box.left ||
            event.clientX > box.right ||
            event.clientY < box.top ||
            event.clientY > box.bottom
          )
            onClose();
        }
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
        if (event.key === "Tab") {
          const nodes = Array.from(
            ref.current?.querySelectorAll<HTMLElement>(
              'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),[tabindex="0"]',
            ) || [],
          ).filter(node=>node.tabIndex>=0&&node.getClientRects().length>0&&!node.closest('[hidden],[inert],[aria-hidden="true"]'));
          const first = nodes[0],
            last = nodes.at(-1);
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }
      }}
    >
      <header className="dialog-header">
        <h2 id={titleId}>{title}</h2>
        <div className="dialog-header-actions">
          {headerActions}
          <button
            type="button"
            className="icon-button"
            aria-label="关闭弹窗"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
      </header>
      {status && <div className="dialog-status">{status}</div>}
      <div className="dialog-body" ref={body} style={{height:bodyHeight}}><div className="dialog-content" ref={content}>{children}</div></div>
      {footer && <footer className="dialog-footer">{footer}</footer>}
    </dialog>
  );
}
