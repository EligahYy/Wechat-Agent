import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
export function Dialog({
  open,
  title,
  onClose,
  children,
  footer,
  headerActions,
  wide = false,
}: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  headerActions?: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null),
    previous = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const [closing, setClosing] = useState(false);
  useEffect(() => {
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
          );
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
      <div className="dialog-body">{children}</div>
      {footer && <footer className="dialog-footer">{footer}</footer>}
    </dialog>
  );
}
