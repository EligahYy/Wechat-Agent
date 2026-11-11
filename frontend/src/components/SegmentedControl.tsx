import { useId } from "react";
import { motion } from "motion/react";
export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  label,
  kind = "pill",
}: {
  value: T;
  options: { value: T; label: string; count?: number }[];
  onChange: (value: T) => void;
  label: string;
  kind?: "pill" | "tabs";
}) {
  const id = useId();
  return (
    <div
      className={`segments segments-${kind}`}
      role="tablist"
      aria-label={label}
    >
      {options.map((option, index) => (
        <button
          type="button"
          role="tab"
          aria-selected={value === option.value}
          tabIndex={value === option.value ? 0 : -1}
          key={option.value}
          onClick={() => onChange(option.value)}
          onKeyDown={(event) => {
            if (
              ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
            ) {
              event.preventDefault();
              const next =
                event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? options.length - 1
                    : (index +
                        (event.key === "ArrowRight" ? 1 : -1) +
                        options.length) %
                      options.length;
              onChange(options[next].value);
              (
                event.currentTarget.parentElement?.children[next] as HTMLElement
              )?.focus();
            }
          }}
        >
          {value === option.value && (
            <motion.span
              className="segment-indicator"
              layoutId={id}
              transition={{ type: "spring", stiffness: 460, damping: 38 }}
            />
          )}
          <span className="segment-label">
            {option.label}
            {option.count !== undefined && (
              <span className="count">{option.count}</span>
            )}
          </span>
        </button>
      ))}
    </div>
  );
}
