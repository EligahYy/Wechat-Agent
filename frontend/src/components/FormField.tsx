import {
  useId,
  useLayoutEffect,
  useRef,
  type InputHTMLAttributes,
  type ReactNode,
  type ChangeEvent,
  type KeyboardEvent,
  type FocusEvent,
} from "react";

type Props = Omit<
  InputHTMLAttributes<HTMLInputElement | HTMLTextAreaElement>,
  "onChange" | "onKeyDown" | "onBlur"
> & {
  label: string;
  multiline?: boolean;
  error?: string;
  leading?: ReactNode;
  trailing?: ReactNode;
  onChange?: (
    event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => void;
  onBlur?: (event: FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  onKeyDown?: (
    event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => void;
};
export function FormField({
  label,
  multiline,
  error,
  leading,
  trailing,
  id,
  className = "",
  type = "text",
  ...props
}: Props) {
  const generated = useId(),
    fieldId = id || generated;
  const textarea = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    if (textarea.current) {
      textarea.current.style.height = "auto";
      textarea.current.style.height =
        Math.max(48, textarea.current.scrollHeight) + "px";
    }
  }, [props.value]);
  const common = {
    ...props,
    id: fieldId,
    "aria-invalid": !!error,
    "aria-describedby": error ? `${fieldId}-error` : undefined,
    className: `form-control ${className}`,
  };
  return (
    <div className={`field ${error ? "field-error" : ""}`}>
      <label htmlFor={fieldId}>{label}</label>
      <div className="field-shell">
        {leading && <span className="field-leading">{leading}</span>}
        {multiline ? (
          <textarea {...common} ref={textarea} rows={2} />
        ) : (
          <input {...common} type={type} />
        )}{" "}
        {trailing && <span className="field-trailing">{trailing}</span>}
      </div>
      {error && (
        <span id={`${fieldId}-error`} role="alert" className="field-message">
          {error}
        </span>
      )}
    </div>
  );
}
