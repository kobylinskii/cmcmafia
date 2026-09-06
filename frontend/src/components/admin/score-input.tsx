"use client";

import { Minus, Plus } from "@phosphor-icons/react/dist/ssr";

/**
 * Поле балла со стрелочками. Родные спиннеры <input type="number"> здесь не
 * годятся: они занимают фиксированные ~20px и в узких колонках таблицы
 * наезжают прямо на значение, особенно когда браузер показывает дробную часть
 * через запятую (русская локаль) -- "0,5" превращалось в "0," со стрелочками
 * поверх пятёрки. Поэтому свои кнопки: они снаружи поля, а не поверх него, и
 * шаг у них тот же, что принимает бэкенд (см. app/schemas/game.py).
 */
export function ScoreInput({
  value,
  onChange,
  step,
  min,
  max,
  label,
  placeholder = "—",
  className = "",
  disabled = false,
}: {
  value: string;
  onChange: (next: string) => void;
  step: number;
  min: number;
  max: number;
  label: string;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}) {
  // Пустое поле -- это «не заполнено», а не ноль: у Ci, ЖК, СК и удалений
  // пусто и ноль означают разное (см. колонку ЛХ в публичной таблице).
  const current = value === "" ? null : Number(value);

  function nudge(direction: 1 | -1) {
    const base = current ?? (direction > 0 ? min - step : min);
    const next = Math.min(max, Math.max(min, base + direction * step));
    // Округление до шага: 0.1 + 0.2 в двоичной плавающей точке даёт
    // 0.30000000000000004, и бэкенд отбил бы такое значение как некратное.
    const snapped = Math.round(next / step) * step;
    onChange(String(Number(snapped.toFixed(4))));
  }

  const btn =
    "flex h-8 w-7 shrink-0 items-center justify-center rounded-md border border-ink-700 " +
    "bg-ink-850 text-ink-300 hover:bg-ink-800 hover:text-ink-50 " +
    "disabled:opacity-30 disabled:hover:bg-ink-850 disabled:hover:text-ink-300";

  return (
    <div className={`flex items-center justify-center gap-1 ${className}`}>
      <button
        type="button"
        className={btn}
        onClick={() => nudge(-1)}
        disabled={disabled || (current !== null && current <= min)}
        aria-label={`${label}: уменьшить на ${step}`}
        tabIndex={-1}
      >
        <Minus size={12} weight="bold" />
      </button>
      <input
        aria-label={label}
        // Фиксированная ширина, а не w-full: во flex-строке с двумя кнопками
        // поле с min-w-0 схлопывалось до 15px и в него было не попасть.
        className="no-spinner w-12 shrink-0 rounded-lg border border-ink-700 bg-ink-900 px-1 py-2 text-center text-sm text-ink-50 disabled:opacity-40"
        type="number"
        inputMode="decimal"
        step={step}
        min={min}
        max={max}
        placeholder={placeholder}
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        className={btn}
        onClick={() => nudge(1)}
        disabled={disabled || (current !== null && current >= max)}
        aria-label={`${label}: увеличить на ${step}`}
        tabIndex={-1}
      >
        <Plus size={12} weight="bold" />
      </button>
    </div>
  );
}
