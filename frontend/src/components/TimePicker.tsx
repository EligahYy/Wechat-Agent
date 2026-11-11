import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { Clock3 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { FormField } from "./FormField";
const pad = (value: number) => String(value).padStart(2, "0");
export function TimePicker({
  value,
  onCommit,
  disabled = false,
}: {
  value: string;
  onCommit: (value: string) => void | Promise<void>;
  disabled?: boolean;
}) {
  const [text, setText] = useState(value),
    [error, setError] = useState(""),
    [open, setOpen] = useState(false),
    [above, setAbove] = useState(false),
    [draft, setDraft] = useState(value);
  const root = useRef<HTMLDivElement>(null),
    trigger = useRef<HTMLButtonElement>(null),
    panel = useRef<HTMLDivElement>(null);
  const committing = useRef(false);
  const clockPointer = useRef(false);
  useEffect(() => {
    setText(value);
  }, [value]);
  const dismiss = () => {
    setOpen(false);
    setDraft(value);
    setText(value);
    setError("");
    trigger.current?.focus();
  };
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) dismiss();
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open, value]);
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);
  useLayoutEffect(() => {
    if (open) {
      setAbove(
        window.innerHeight -
          (root.current?.getBoundingClientRect().bottom || 0) <
          390,
      );
      const selected = panel.current?.querySelectorAll<HTMLElement>(
        '[aria-selected="true"]',
      );
      selected?.forEach((option) => {
        const list = option.parentElement;
        if (list)
          list.scrollTop =
            option.offsetTop -
            list.offsetTop -
            list.clientHeight / 2 +
            option.clientHeight / 2;
      });
      selected?.[0]?.focus();
    }
  }, [open]);
  const commit = async (next: string) => {
    if (committing.current) return;
    if (!/^(?:[01]?\d|2[0-3]):[0-5]\d$/.test(next)) {
      setError("请输入有效时间，如 09:05");
      return;
    }
    const normalized = next.padStart(5, "0");
    committing.current = true;
    setError("");
    try {
      await onCommit(normalized);
      setText(normalized);
    } catch {
      setError("时间保存失败，请重试");
    } finally {
      committing.current = false;
    }
  };
  const update = (part: number, next: number) => {
    const pieces = draft.split(":");
    pieces[part] = pad(next);
    setDraft(pieces.join(":"));
  };
  const optionKey = (
    event: KeyboardEvent<HTMLButtonElement>,
    part: number,
    index: number,
    total: number,
  ) => {
    if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? total - 1
          : (index + (event.key === "ArrowDown" ? 1 : -1) + total) % total;
    update(part, next);
    (event.currentTarget.parentElement?.children[next] as HTMLElement)?.focus();
  };
  return (
    <div className="time-picker" ref={root}>
      <FormField
        label="每天开始时间"
        value={text}
        error={error}
        disabled={disabled}
        inputMode="numeric"
        autoComplete="off"
        onChange={(event) => setText(event.target.value)}
        onBlur={(event) => {
          if (
            !open &&
            text !== value &&
            !(event.relatedTarget === trigger.current && clockPointer.current)
          )
            void commit(text);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void commit(text);
          }
        }}
        trailing={
          <button
            ref={trigger}
            disabled={disabled}
            type="button"
            className="icon-button clock-trigger"
            aria-label="选择开始时间"
            aria-haspopup="dialog"
            aria-expanded={open}
            onPointerDown={() => {
              clockPointer.current = true;
            }}
            onPointerCancel={() => {
              clockPointer.current = false;
            }}
            onClick={() => {
              clockPointer.current = false;
              setDraft(
                /^(?:[01]?\d|2[0-3]):[0-5]\d$/.test(text)
                  ? text.padStart(5, "0")
                  : value,
              );
              setOpen(!open);
            }}
          >
            <Clock3 size={18} />
          </button>
        }
      />
      <AnimatePresence>
        {open && (
          <motion.div
            ref={panel}
            role="dialog"
            aria-label="选择开始时间"
            className={`time-popover glass ${above ? "popover-above" : ""}`}
            initial={{ opacity: 0, y: above ? 6 : -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: above ? 6 : -6, scale: 0.98 }}
            transition={{ duration: 0.18 }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                dismiss();
              }
              if (event.key === "Tab") {
                const controls = Array.from(
                  panel.current?.querySelectorAll<HTMLElement>(
                    'button:not([tabindex="-1"])',
                  ) || [],
                );
                if (
                  !event.shiftKey &&
                  document.activeElement === controls.at(-1)
                ) {
                  event.preventDefault();
                  controls[0]?.focus();
                } else if (
                  event.shiftKey &&
                  document.activeElement === controls[0]
                ) {
                  event.preventDefault();
                  controls.at(-1)?.focus();
                }
              }
            }}
          >
            <header>
              <strong>开始时间</strong>
              <span>北京时间</span>
            </header>
            <div className="time-columns">
              {[24, 60].map((total, part) => (
                <div key={part}>
                  <div className="time-column-label">
                    {part === 0 ? "小时" : "分钟"}
                  </div>
                  <div
                    className="time-options"
                    role="listbox"
                    aria-label={part === 0 ? "小时" : "分钟"}
                  >
                    {Array.from({ length: total }, (_, index) => (
                      <button
                        type="button"
                        role="option"
                        aria-label={`${pad(index)} ${part === 0 ? "时" : "分"}`}
                        aria-selected={Number(draft.split(":")[part]) === index}
                        tabIndex={
                          Number(draft.split(":")[part]) === index ? 0 : -1
                        }
                        key={index}
                        onClick={() => update(part, index)}
                        onKeyDown={(event) =>
                          optionKey(event, part, index, total)
                        }
                      >
                        {pad(index)}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <footer>
              <button
                type="button"
                className="button secondary"
                onClick={dismiss}
              >
                取消
              </button>
              <button
                type="button"
                className="button primary"
                onClick={() => {
                  void commit(draft);
                  setOpen(false);
                  trigger.current?.focus();
                }}
              >
                应用
              </button>
            </footer>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
