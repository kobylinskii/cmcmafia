import clsx from "clsx";
import { ReactNode } from "react";
import type { GameResult } from "@/types/api";
import { RESULT_LABELS } from "@/types/api";

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: "neutral" | "brand" | "outline";
  className?: string;
}) {
  const tones = {
    neutral: "bg-ink-800 text-ink-200",
    brand: "bg-brand-500 text-ink-50",
    outline: "border border-ink-600 text-ink-200",
  };
  return (
    <span
      className={clsx(
        // px-3 py-1 text-xs при базовом кегле 17px давало 12.75px --
        // плашка читалась как служебная метка, хотя формат игры и её исход
        // это главные данные строки. Поднято на шаг, до одного уровня с
        // сопровождающим текстом.
        "inline-flex items-center rounded-pill px-3.5 py-1.5 text-sm font-medium tracking-wide",
        tones[tone],
        className
      )}
    >
      {children}
    </span>
  );
}

export function ResultBadge({ result }: { result: GameResult | null }) {
  if (!result) return <Badge tone="neutral">Не оценена</Badge>;
  const tone = result === "draw" ? "outline" : "brand";
  return <Badge tone={tone}>{RESULT_LABELS[result]}</Badge>;
}
