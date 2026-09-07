"use client";

import clsx from "clsx";

/** Ряд pill-кнопок с одним активным. Замена range-слайдеру: тот слал
 * навигацию на каждый тик и упирался в rate limit публичного API. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div className={clsx("inline-flex rounded-pill border border-ink-700 bg-ink-850 p-1", className)}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
          className={clsx(
            "rounded-pill px-3.5 py-1.5 text-sm font-medium transition-colors active:translate-y-px",
            value === option.value ? "bg-brand-600 text-ink-50" : "text-ink-300 hover:text-ink-50"
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
